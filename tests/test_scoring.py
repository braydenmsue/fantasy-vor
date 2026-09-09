"""Consistency (Score 3) and ensemble combination (spec section 3)."""

from __future__ import annotations

import pandas as pd
import pytest

from fantasy_vor.config import EnsembleWeights
from fantasy_vor.scoring import consistency, ensemble


def weekly_log(player_id: int, points: list[float]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "player_id": player_id,
            "season": 2025,
            "week": range(1, len(points) + 1),
            "ppr_pts": points,
        }
    )


def test_steady_player_scores_higher_than_boom_bust():
    steady = weekly_log(1, [15.0, 15.0, 15.0, 15.0, 15.0, 15.0])
    swingy = weekly_log(2, [30.0, 2.0, 28.0, 1.0, 32.0, 2.0])

    scores = consistency.compute_consistency(pd.concat([steady, swingy])).set_index("player_id")
    assert scores.loc[1, "consistency"] > scores.loc[2, "consistency"]


def test_perfectly_flat_production_scores_one():
    scores = consistency.compute_consistency(weekly_log(1, [12.0] * 6))
    assert float(scores.iloc[0]["consistency"]) == pytest.approx(1.0)


def test_floor_is_the_25th_percentile_week():
    scores = consistency.compute_consistency(weekly_log(1, [10.0, 20.0, 30.0, 40.0]))
    assert float(scores.iloc[0]["floor_ppg"]) == pytest.approx(17.5)


def test_thin_samples_get_no_consistency_score():
    """Fewer than four games played is not enough to judge steadiness."""
    scores = consistency.compute_consistency(weekly_log(1, [10.0, 20.0]))
    assert pd.isna(scores.iloc[0]["consistency"])


def test_missing_weeks_are_not_treated_as_zero_point_games():
    """A bye or an inactive is an availability question, not a consistency one.

    Score 2 already handles games played; counting the gap as a 0 here would
    penalize the same thing twice.
    """
    with_gaps = weekly_log(1, [15.0, 0.0, 15.0, 0.0, 15.0, 15.0])
    scores = consistency.compute_consistency(with_gaps)
    assert int(scores.iloc[0]["weeks_played"]) == 4
    assert float(scores.iloc[0]["consistency"]) == pytest.approx(1.0)


def test_empty_weekly_log_is_handled():
    empty = pd.DataFrame(columns=["player_id", "season", "week", "ppr_pts"])
    assert consistency.compute_consistency(empty).empty


# --------------------------------------------------------------------------
# Ensemble
# --------------------------------------------------------------------------

def test_normalize_maps_to_0_100():
    scaled = ensemble.normalize(pd.Series([0.0, 5.0, 10.0]))
    assert list(scaled) == [0.0, 50.0, 100.0]


def test_normalize_handles_a_flat_series():
    """No spread means no information, so everyone sits at the midpoint."""
    scaled = ensemble.normalize(pd.Series([7.0, 7.0, 7.0]))
    assert list(scaled) == [50.0, 50.0, 50.0]


def test_v1_weights_zero_out_scores_2_and_3(pool, config):
    """Scores 2 and 3 are tracked but must not move a v1 recommendation."""
    weights = EnsembleWeights()
    assert weights.games_adjusted == 0.0
    assert weights.consistency == 0.0

    baseline = ensemble.compute_ensemble(pool, weights)

    tampered = pool.copy()
    tampered["consistency"] = 0.99  # would dominate if it carried any weight
    tampered["games"] = 1.0
    shifted = ensemble.compute_ensemble(tampered, weights)

    assert list(baseline["player_id"]) == list(shifted["player_id"])


def test_weights_are_renormalized():
    weights = EnsembleWeights(vor=6.0, games_adjusted=0.0, consistency=0.0, adp_gap=1.0)
    normalized = weights.normalized()
    assert normalized.vor + normalized.adp_gap == pytest.approx(1.0)
    # The 6:1 ratio between VOR and the ADP gap must survive renormalization.
    assert normalized.vor / normalized.adp_gap == pytest.approx(6.0)


def test_zero_weights_are_rejected():
    with pytest.raises(ValueError, match="positive"):
        EnsembleWeights(vor=0, games_adjusted=0, consistency=0, adp_gap=0).normalized()


def test_adp_gap_rewards_players_the_market_undervalues(pool, config):
    """Score 4 is ADP rank minus VOR rank, so positive means a value pick."""
    scored = ensemble.compute_scores(pool)
    row = scored.iloc[0]
    assert row["raw_adp_gap"] == row["adp_rank"] - row["vor_rank"]
