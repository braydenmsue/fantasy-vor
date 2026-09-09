"""Scrape FantasyPros season and weekly stat tables.

The stats pages are server-rendered: each one contains a single ``<table
id="data">`` whose rows carry a stable FantasyPros player id in the anchor class
(``fp-id-17298``). That id is the same one the ADP feed uses, so the two sources
join on it directly with no name matching.

Column layout differs per position (a QB table has passing columns, a DST table
has sack/INT columns) but every table ends with the same four columns:
``G, FPTS, FPTS/G, ROST``. Reading from the right is therefore position-agnostic.
"""

from __future__ import annotations

import logging
import re
import time

import pandas as pd
import requests
from bs4 import BeautifulSoup

log = logging.getLogger(__name__)

BASE_URL = "https://www.fantasypros.com/nfl/stats/{position}.php"

# FantasyPros uses "dst" in the URL but we normalize the position label to DST.
URL_POSITIONS = {"QB": "qb", "RB": "rb", "WR": "wr", "TE": "te", "K": "k", "DST": "dst"}

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

REQUEST_DELAY = 1.0  # be a polite scraper
_FP_ID = re.compile(r"fp-id-(\d+)")
_TEAM = re.compile(r"\(([A-Z]{2,3})\)")


def _to_float(text: str) -> float:
    """Parse a FantasyPros stat cell ('1,202', '99.5%', '-') to a float."""
    cleaned = text.strip().replace(",", "").replace("%", "")
    if not cleaned or cleaned == "-":
        return 0.0
    try:
        return float(cleaned)
    except ValueError:
        return 0.0


def _parse_table(html: str, position: str) -> pd.DataFrame:
    soup = BeautifulSoup(html, "lxml")
    table = soup.find("table", id="data")
    if table is None:
        raise ValueError(f"no <table id='data'> found on the {position} stats page")

    rows = []
    body = table.find("tbody")
    for tr in body.find_all("tr"):
        link = tr.find("a", class_="player-name")
        if link is None:
            continue
        match = _FP_ID.search(" ".join(link.get("class", [])))
        if match is None:
            continue

        cells = tr.find_all("td")
        if len(cells) < 5:
            continue

        # Last four columns are always G, FPTS, FPTS/G, ROST.
        games, ppr_pts, ppg = (_to_float(c.get_text()) for c in cells[-4:-1])

        label = tr.find("td", class_="player-label").get_text()
        team_match = _TEAM.search(label)

        rows.append(
            {
                "player_id": int(match.group(1)),
                "name": link.get("fp-player-name") or link.get_text(strip=True),
                "team": team_match.group(1) if team_match else "",
                "position": position,
                "games": games,
                "ppr_pts": ppr_pts,
                "ppg": ppg,
            }
        )

    return pd.DataFrame(rows)


def _fetch(position: str, year: int, week: int | None, session: requests.Session) -> str:
    params = {"scoring": "PPR", "year": year}
    if week is not None:
        params["range"] = "week"
        params["week"] = week

    url = BASE_URL.format(position=URL_POSITIONS[position])
    response = session.get(url, params=params, headers=HEADERS, timeout=30)
    response.raise_for_status()
    return response.text


def fetch_season_stats(year: int, positions: tuple[str, ...] = tuple(URL_POSITIONS)) -> pd.DataFrame:
    """Season totals for every position.

    Returns one row per player with ``player_id, name, team, position, games,
    ppr_pts, ppg``.
    """
    frames = []
    with requests.Session() as session:
        for i, position in enumerate(positions):
            if i:
                time.sleep(REQUEST_DELAY)
            html = _fetch(position, year, None, session)
            frame = _parse_table(html, position)
            log.info("%s %d: %d players", position, year, len(frame))
            frames.append(frame)

    return pd.concat(frames, ignore_index=True)


def fetch_weekly_stats(
    year: int,
    weeks: range = range(1, 19),
    positions: tuple[str, ...] = tuple(URL_POSITIONS),
) -> pd.DataFrame:
    """Per-week point log, used by the consistency score.

    One request per (position, week) rather than per player -- roughly 108
    requests for a full season.
    """
    frames = []
    with requests.Session() as session:
        for position in positions:
            for week in weeks:
                time.sleep(REQUEST_DELAY)
                try:
                    html = _fetch(position, year, week, session)
                except requests.HTTPError as exc:
                    log.warning("skipping %s week %d: %s", position, week, exc)
                    continue
                frame = _parse_table(html, position)
                if frame.empty:
                    continue
                frames.append(
                    frame.assign(season=year, week=week)[
                        ["player_id", "season", "week", "ppr_pts"]
                    ]
                )
            log.info("%s %d: weekly logs done", position, year)

    if not frames:
        return pd.DataFrame(columns=["player_id", "season", "week", "ppr_pts"])
    return pd.concat(frames, ignore_index=True)
