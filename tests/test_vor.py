"""VOR and replacement-level math (spec section 2)."""

from __future__ import annotations

import pandas as pd

from fantasy_vor.config import Config, LeagueSettings
from fantasy_vor.scoring import imputation, vor

from .conftest import make_stats


def test_rb_and_wr_share_one_replacement_level(stats, config):
    """The whole point of the pooled flex baseline: RB and WR must match.

    Independent per-position baselines would double-count the FLEX slot.
    """
    levels = vor.compute_replacement_levels(stats, config.league, config.rules.min_games)
    assert levels.by_position["RB"] == levels.by_position["WR"]
    assert levels.by_position["RB"] == levels.flex_replacement_ppg


def test_flex_replacement_is_the_pooled_nth_player(stats, config):
    """Replacement rank is N x (RB + WR + FLEX) over RBs and WRs sorted together."""
    league = config.league
    assert league.flex_pool_size == 12 * (2 + 2 + 1) == 60

    pooled = (
        stats[stats["position"].isin(["RB", "WR"])]
        .sort_values("ppg", ascending=False, ignore_index=True)
    )
    expected = pooled.iloc[59]  # 60th, 1-indexed

    levels = vor.compute_replacement_levels(stats, league, config.rules.min_games)
    assert levels.flex_replacement_ppg == expected["ppg"]
    assert levels.flex_replacement_player == expected["name"]


def test_single_slot_positions_use_rank_n(stats, config):
    """QB and TE replacement is simply the Nth-ranked player at the position."""
    levels = vor.compute_replacement_levels(stats, config.league, config.rules.min_games)

    for position in ("QB", "TE"):
        ranked = (
            stats[stats["position"] == position]
            .sort_values("ppg", ascending=False, ignore_index=True)
        )
        assert levels.by_position[position] == ranked.iloc[11]["ppg"]  # 12th


def test_vor_is_ppg_minus_replacement(stats, config):
    scored = vor.compute_vor(stats, config.league, config.rules.min_games)
    row = scored[scored["name"] == "QB1"].iloc[0]
    assert row["vor"] == row["ppg"] - row["replacement_ppg"]


def test_small_sample_players_cannot_set_the_baseline(config):
    """A sub-9-game player must not drag the replacement level around.

    Here a scrub played 3 games at a huge PPG. If he counted, he would displace
    a real player from the cutoff rank and move the baseline.
    """
    rows = [(i + 1, f"QB{i + 1}", "BUF", "QB", 17.0, 26.0 - i * 0.5) for i in range(20)]
    clean = make_stats(rows)
    polluted = make_stats(rows + [(999, "Scrub", "BUF", "QB", 3.0, 99.0)])

    league = LeagueSettings(n_teams=12)
    before = vor.compute_replacement_levels(clean, league, 9).by_position["QB"]
    after = vor.compute_replacement_levels(polluted, league, 9).by_position["QB"]
    assert before == after


def test_small_sample_players_get_no_vor(config):
    rows = [(i + 1, f"QB{i + 1}", "BUF", "QB", 17.0, 26.0 - i * 0.5) for i in range(20)]
    rows.append((999, "Scrub", "BUF", "QB", 3.0, 99.0))
    scored = vor.compute_vor(make_stats(rows), LeagueSettings(n_teams=12), 9)
    assert pd.isna(scored[scored["name"] == "Scrub"].iloc[0]["vor"])


def test_imputation_fills_missing_vor_from_adp(stats, config):
    """Rookies have no prior season, so their VOR comes off the ADP curve."""
    scored = vor.compute_vor(stats, config.league, config.rules.min_games)
    scored["adp_rank"] = range(1, len(scored) + 1)

    rookie = pd.DataFrame(
        [
            {
                "player_id": 9999,
                "name": "Rookie RB",
                "team": "ARI",
                "position": "RB",
                "games": 0.0,
                "ppg": 0.0,
                "ppr_pts": 0.0,
                "replacement_ppg": 11.0,
                "vor": pd.NA,
                "vor_imputed": False,
                "adp_rank": 15,
            }
        ]
    )
    combined = pd.concat([scored, rookie], ignore_index=True)
    combined["vor"] = combined["vor"].astype("Float64")

    filled = imputation.impute_missing_vor(combined)
    row = filled[filled["name"] == "Rookie RB"].iloc[0]

    assert bool(row["vor_imputed"])
    assert pd.notna(row["vor"])
    # An ADP-15 player should land above the replacement-level crowd.
    assert float(row["vor"]) > 0


def test_imputed_vor_decreases_with_adp(stats, config):
    """The ADP curve must be monotone -- a later pick cannot imply more value."""
    scored = vor.compute_vor(stats, config.league, config.rules.min_games)
    scored["adp_rank"] = range(1, len(scored) + 1)
    slope, _ = imputation.fit_adp_vor_curve(scored)
    assert slope < 0
