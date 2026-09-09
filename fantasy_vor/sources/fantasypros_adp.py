"""FantasyPros consensus ADP.

The public ADP page (``/nfl/adp/ppr-overall.php``) renders its table client-side,
so there is nothing to scrape out of the HTML. The Vue app is backed by this
JSON feed, which needs no auth and carries three things we want:

* ``rank_ecr`` / ``rank_ave`` -- consensus ADP rank and average draft position
* ``player_bye_week``         -- bye weeks, which the spec needs for rule 9
* ``player_id``               -- the same id the stats pages expose, so the join
                                between ADP and season stats is exact
"""

from __future__ import annotations

import logging

import pandas as pd
import requests

log = logging.getLogger(__name__)

ADP_URL = "https://partners.fantasypros.com/api/v1/consensus-rankings.php"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
}

# The feed carries a handful of defensive players (LB/CB) for IDP leagues.
KEEP_POSITIONS = {"QB", "RB", "WR", "TE", "K", "DST"}


def _to_float(value, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def fetch_adp(year: int, scoring: str = "PPR") -> pd.DataFrame:
    """Consensus ADP for the given draft year.

    Returns ``player_id, name, team, position, adp_rank, adp, bye_week, tier``,
    sorted by ADP rank.
    """
    params = {
        "sport": "NFL",
        "year": year,
        "week": 0,
        "position": "ALL",
        "scoring": scoring,
        "type": "ADP",
    }
    response = requests.get(ADP_URL, params=params, headers=HEADERS, timeout=30)
    response.raise_for_status()
    payload = response.json()

    log.info(
        "ADP feed: %s players, %s experts, last updated %s",
        payload.get("count"),
        payload.get("total_experts"),
        payload.get("last_updated"),
    )

    rows = []
    for player in payload.get("players", []):
        position = player.get("player_position_id")
        if position not in KEEP_POSITIONS:
            continue

        team = (player.get("player_team_id") or "").strip()
        if not team or team == "FA":
            # Free agents and retired players are undraftable; they are also
            # exactly the rows the feed leaves without a bye week.
            continue

        rows.append(
            {
                "player_id": int(player["player_id"]),
                "name": player["player_name"],
                "team": team,
                "position": position,
                "adp_rank": int(player["rank_ecr"]),
                "adp": _to_float(player.get("rank_ave"), default=float(player["rank_ecr"])),
                "bye_week": int(_to_float(player.get("player_bye_week"), default=0)),
                "tier": int(_to_float(player.get("tier"), default=0)),
            }
        )

    frame = pd.DataFrame(rows).sort_values("adp_rank", ignore_index=True)
    log.info("kept %d draftable players", len(frame))
    return frame
