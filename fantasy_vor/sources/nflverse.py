"""Team rushing volume, used by the run-heavy RB boost.

The rule was specified against pro-football-reference's team rushing-attempt
ranks, but PFR sits behind a Cloudflare challenge that returns 403 to plain HTTP
clients. nflverse publishes the same underlying numbers as flat CSVs on GitHub
releases, which is both reachable and considerably more stable.

Two bases are available:

``rb_carries`` (default)
    Carries by players listed at RB, summed per team. This is the better proxy
    for running back opportunity.

``team_carries``
    Total team rushing attempts -- the literal PFR-page number, which includes
    quarterback runs.

The two disagree sharply. In 2025, ranking by total team attempts puts WAS 9th,
JAX 8th and NE 6th on the strength of quarterback rushing, while their running
backs rank 24th, 19th and 17th; DET, LA and ATL go the other way (21st/17th/12th
by team attempts, 5th/4th/2nd by RB carries). Four of the top ten "run-heavy"
teams do not actually feed their backs, which is why RB carries is the default.
"""

from __future__ import annotations

import io
import logging

import pandas as pd
import requests

log = logging.getLogger(__name__)

RELEASE = "https://github.com/nflverse/nflverse-data/releases/download"
PLAYER_STATS_URL = RELEASE + "/stats_player/stats_player_reg_{year}.csv"
TEAM_STATS_URL = RELEASE + "/stats_team/stats_team_reg_{year}.csv"

# nflverse and FantasyPros disagree on a few team abbreviations.
# Left side is nflverse, right side is the FantasyPros code we join against.
TEAM_ALIASES = {
    "LA": "LAR",
    "JAX": "JAC",
    "OAK": "LV",
    "SD": "LAC",
    "STL": "LAR",
    "WSH": "WAS",
}


def _get_csv(url: str) -> pd.DataFrame:
    response = requests.get(url, timeout=90)
    response.raise_for_status()
    return pd.read_csv(io.StringIO(response.text))


def _normalize_team(series: pd.Series) -> pd.Series:
    return series.astype(str).str.strip().replace(TEAM_ALIASES)


def fetch_rush_ranks(year: int) -> pd.DataFrame:
    """Per-team rushing volume ranks.

    Returns ``team, rb_carries, rb_carry_rank, team_carries, team_carry_rank``
    where rank 1 is the most rushing volume.
    """
    players = _get_csv(PLAYER_STATS_URL.format(year=year))
    rbs = players[players["position"] == "RB"]
    rb_carries = (
        rbs.groupby(_normalize_team(rbs["recent_team"]))["carries"]
        .sum()
        .rename("rb_carries")
        .reset_index()
        .rename(columns={"recent_team": "team"})
    )
    rb_carries["rb_carry_rank"] = rb_carries["rb_carries"].rank(
        ascending=False, method="min"
    ).astype(int)

    teams = _get_csv(TEAM_STATS_URL.format(year=year))
    team_carries = (
        teams.assign(team=_normalize_team(teams["team"]))[["team", "carries"]]
        .rename(columns={"carries": "team_carries"})
    )
    team_carries["team_carry_rank"] = team_carries["team_carries"].rank(
        ascending=False, method="min"
    ).astype(int)

    frame = rb_carries.merge(team_carries, on="team", how="outer")
    log.info("rush ranks for %d teams (%d)", len(frame), year)
    return frame.sort_values("rb_carry_rank", ignore_index=True)


def run_heavy_teams(rush_ranks: pd.DataFrame, top_n: int, basis: str) -> set[str]:
    """The set of team codes considered run-heavy under the configured basis."""
    column = "rb_carry_rank" if basis == "rb_carries" else "team_carry_rank"
    return set(rush_ranks.loc[rush_ranks[column] <= top_n, "team"])
