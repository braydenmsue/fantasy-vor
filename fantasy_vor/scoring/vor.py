"""Value Over Replacement (spec section 2).

The important subtlety is the replacement baseline for RB and WR. Because both
positions compete for the same FLEX slot, a marginal RB and a marginal WR are
true substitutes, so they must share a single pooled replacement rank. Computing
independent RB and WR baselines double-counts the FLEX slot and inflates both.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import pandas as pd

from ..config import FLEX_POSITIONS, LeagueSettings

log = logging.getLogger(__name__)


@dataclass
class ReplacementLevels:
    """The replacement PPG used for each position, plus how it was derived."""

    by_position: dict[str, float]
    flex_replacement_ppg: float
    flex_replacement_player: str

    def for_position(self, position: str) -> float:
        return self.by_position[position]


def _nth_ppg(frame: pd.DataFrame, rank: int) -> tuple[float, str]:
    """PPG of the ``rank``-th best player in ``frame`` (1-indexed), and who it is.

    Falls back to the worst available player when the pool is shallower than the
    requested rank, which can happen for K/DST in a deep league.
    """
    ordered = frame.sort_values("ppg", ascending=False, ignore_index=True)
    if ordered.empty:
        return 0.0, "(no qualifying players)"
    index = min(rank, len(ordered)) - 1
    row = ordered.iloc[index]
    return float(row["ppg"]), str(row["name"])


def eligible_for_baseline(stats: pd.DataFrame, min_games: int) -> pd.DataFrame:
    """Players who may set a replacement level.

    The spec excludes anyone under ``min_games`` games *before* replacement rank
    is computed, so a small-sample player cannot drag a baseline around.
    """
    return stats[stats["games"] >= min_games]


def compute_replacement_levels(
    stats: pd.DataFrame, league: LeagueSettings, min_games: int = 9
) -> ReplacementLevels:
    """Replacement PPG per position."""
    qualified = eligible_for_baseline(stats, min_games)

    # RB and WR pooled together, sorted by PPG, cut at N x (RB + WR + FLEX).
    flex_pool = qualified[qualified["position"].isin(FLEX_POSITIONS)]
    flex_ppg, flex_name = _nth_ppg(flex_pool, league.flex_pool_size)
    log.info(
        "flex replacement: rank %d of pooled RB/WR = %s (%.2f ppg)",
        league.flex_pool_size,
        flex_name,
        flex_ppg,
    )

    by_position: dict[str, float] = {"RB": flex_ppg, "WR": flex_ppg}

    # One starting slot per team, so the replacement rank is simply N.
    for position in ("QB", "TE", "K", "DST"):
        pool = qualified[qualified["position"] == position]
        ppg, name = _nth_ppg(pool, league.n_teams)
        by_position[position] = ppg
        log.info(
            "%s replacement: rank %d = %s (%.2f ppg)", position, league.n_teams, name, ppg
        )

    return ReplacementLevels(
        by_position=by_position,
        flex_replacement_ppg=flex_ppg,
        flex_replacement_player=flex_name,
    )


def compute_vor(
    stats: pd.DataFrame, league: LeagueSettings, min_games: int = 9
) -> pd.DataFrame:
    """Attach ``vor`` and ``replacement_ppg`` to the season stats.

    Players below the games threshold are kept in the frame but get a null VOR --
    they are handed to the imputation step rather than silently dropped, because
    that set includes rookies and stars who missed most of a season.
    """
    levels = compute_replacement_levels(stats, league, min_games)

    frame = stats.copy()
    frame["replacement_ppg"] = frame["position"].map(levels.by_position)
    frame["vor"] = frame["ppg"] - frame["replacement_ppg"]
    frame["vor_imputed"] = False

    # Below the games threshold the single-season sample is not trustworthy.
    small_sample = frame["games"] < min_games
    frame.loc[small_sample, "vor"] = pd.NA
    frame["vor"] = frame["vor"].astype("Float64")

    log.info(
        "VOR computed for %d players, %d held back as small-sample",
        int((~small_sample).sum()),
        int(small_sample.sum()),
    )
    return frame
