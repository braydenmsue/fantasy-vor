"""Combine the four scores into a single draft-priority number (spec section 3).

Each score is normalized to 0-100 across the player pool before weighting, so a
raw VOR in points and an ADP-rank gap in picks can be summed meaningfully.
"""

from __future__ import annotations

import logging

import pandas as pd

from ..config import EnsembleWeights

log = logging.getLogger(__name__)

SCORE_COLUMNS = {
    "vor": "score_vor",
    "games_adjusted": "score_games_adjusted",
    "consistency": "score_consistency",
    "adp_gap": "score_adp_gap",
}


def normalize(series: pd.Series) -> pd.Series:
    """Scale to 0-100. A flat series maps to 50 rather than dividing by zero."""
    numeric = pd.to_numeric(series, errors="coerce").astype(float)
    low, high = numeric.min(), numeric.max()
    if pd.isna(low) or pd.isna(high) or high == low:
        return pd.Series(50.0, index=series.index)
    return (numeric - low) / (high - low) * 100.0


def compute_scores(frame: pd.DataFrame, season_games: int = 17) -> pd.DataFrame:
    """Attach the four raw scores and their normalized 0-100 versions.

    Score 1  raw VOR
    Score 2  VOR scaled by availability
    Score 3  weekly consistency
    Score 4  how far the market's ADP trails our VOR rank
    """
    result = frame.copy()

    result["raw_vor"] = pd.to_numeric(result["vor"], errors="coerce")
    result["raw_games_adjusted"] = result["raw_vor"] * (
        result.get("games", season_games).fillna(0) / season_games
    )
    result["raw_consistency"] = pd.to_numeric(
        result.get("consistency", pd.Series(pd.NA, index=result.index)), errors="coerce"
    )

    # Score 4: positive means the market is drafting them later than our VOR
    # ranking says they deserve.
    result["vor_rank"] = result["raw_vor"].rank(ascending=False, method="min")
    result["raw_adp_gap"] = result["adp_rank"] - result["vor_rank"]

    for key, column in SCORE_COLUMNS.items():
        result[column] = normalize(result[f"raw_{key}"])

    # A player with no weekly log should not be penalized as if they were the
    # least consistent player in the pool.
    result.loc[result["raw_consistency"].isna(), "score_consistency"] = 50.0

    return result


def compute_ensemble(frame: pd.DataFrame, weights: EnsembleWeights) -> pd.DataFrame:
    """Weighted sum of the normalized scores into ``ensemble_score``."""
    scored = compute_scores(frame)
    w = weights.normalized()

    scored["ensemble_score"] = (
        w.vor * scored["score_vor"]
        + w.games_adjusted * scored["score_games_adjusted"]
        + w.consistency * scored["score_consistency"]
        + w.adp_gap * scored["score_adp_gap"]
    )

    log.info(
        "ensemble weights: vor=%.3f games=%.3f consistency=%.3f adp_gap=%.3f",
        w.vor,
        w.games_adjusted,
        w.consistency,
        w.adp_gap,
    )
    return scored.sort_values("ensemble_score", ascending=False, ignore_index=True)
