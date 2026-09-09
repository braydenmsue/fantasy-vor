"""Draft rule behaviour (spec section 4 and the Review addendum)."""

from __future__ import annotations

import pandas as pd
import pytest

from fantasy_vor.config import Config, LeagueSettings, RuleConfig
from fantasy_vor.draft import rules
from fantasy_vor.draft.engine import recommend
from fantasy_vor.draft.state import DraftState

from .conftest import give


def fast_forward(state: DraftState, pool: pd.DataFrame, picks: int) -> None:
    """Burn ``picks`` picks off the board in ADP order."""
    for _ in range(picks):
        state.record(state.available(pool).iloc[0])


# --------------------------------------------------------------------------
# Rule 3 -- position caps
# --------------------------------------------------------------------------

def test_second_qb_is_removed_after_the_first(config, pool):
    state = DraftState(settings=config.league)
    give(state, pool, "QB")

    eligible = rules.eligible_players(state, pool, config)
    assert "QB" not in set(eligible["position"])


def test_second_te_is_removed_after_the_first(config, pool):
    state = DraftState(settings=config.league)
    give(state, pool, "TE")

    eligible = rules.eligible_players(state, pool, config)
    assert "TE" not in set(eligible["position"])


# --------------------------------------------------------------------------
# Rule 4 / 7 / 8 -- kickers and defenses
# --------------------------------------------------------------------------

def test_kickers_and_defenses_are_hidden_early(config, pool):
    state = DraftState(settings=config.league)
    eligible = rules.eligible_players(state, pool, config)
    assert not set(eligible["position"]) & {"K", "DST"}


def test_kicker_comes_in_the_second_to_last_round(small_config, pool):
    """Rule 7: second-to-last round takes the best-ADP kicker."""
    league = small_config.league
    state = DraftState(settings=league)
    kicker_round = league.total_rounds - 1
    fast_forward(state, pool, (kicker_round - 1) * league.n_teams)

    assert state.current_round == kicker_round
    picks = recommend(state, pool, small_config)
    assert picks[0].position == "K"
    assert "Rule 7" in picks[0].reasons[0]


def test_defense_comes_in_the_last_round(small_config, pool):
    """Rule 8: the last round takes the best-ADP defense."""
    league = small_config.league
    state = DraftState(settings=league)
    fast_forward(state, pool, (league.total_rounds - 1) * league.n_teams)

    assert state.current_round == league.total_rounds
    picks = recommend(state, pool, small_config)
    assert picks[0].position == "DST"
    assert "Rule 8" in picks[0].reasons[0]


# --------------------------------------------------------------------------
# Rule 5 -- anti-reach
# --------------------------------------------------------------------------

def test_reach_filter_removes_players_too_far_from_their_adp(config, pool):
    state = DraftState(settings=config.league)
    eligible = rules.eligible_players(state, pool, config)
    filtered, relaxed = rules.apply_reach_filter(state, eligible, config)

    assert not relaxed
    assert filtered["adp_rank"].max() <= state.current_pick + config.rules.reach_threshold


def test_reach_filter_relaxes_rather_than_emptying_the_pool(config, pool):
    """The filter must never leave the engine with nothing to recommend.

    If every remaining player's ADP is far in the future, refusing to reach
    would mean refusing to pick at all, so the guard steps aside instead.
    """
    state = DraftState(settings=config.league)
    distant = pool[pool["adp_rank"] > state.current_pick + config.rules.reach_threshold]

    filtered, relaxed = rules.apply_reach_filter(state, distant, config)

    assert relaxed
    assert len(filtered) == len(distant)


# --------------------------------------------------------------------------
# Rule 2 -- balance guard, and its interaction with rule 5
# --------------------------------------------------------------------------

def test_balance_guard_trips_at_three_apart(config, pool):
    """The guard triggers on a gap of 3, not 2."""
    state = DraftState(settings=config.league)
    wr = pd.Series({"position": "WR"})

    # 1 WR vs 0 RB -- a second WR makes it 2-0, still under the threshold.
    give(state, pool, "WR")
    assert not rules.violates_balance(state, wr, config)

    # 2 WR vs 0 RB -- a third WR would make it 3-0, which trips the guard.
    give(state, pool, "WR")
    assert rules.violates_balance(state, wr, config)


def test_balance_guard_ignores_non_flex_positions(config, pool):
    """QB and TE are not part of the RB/WR balance check."""
    state = DraftState(settings=config.league)
    give(state, pool, "WR", 3)

    for position in ("QB", "TE"):
        assert not rules.violates_balance(state, pd.Series({"position": position}), config)


def test_balance_guard_blocks_a_lopsided_pick(config, pool):
    """4 WR vs 1 RB is the spec's example of an imbalance to guard against."""
    state = DraftState(settings=config.league)
    give(state, pool, "WR", 2)

    wr = pd.Series({"position": "WR"})
    assert rules.violates_balance(state, wr, config)

    rb = pd.Series({"position": "RB"})
    assert not rules.violates_balance(state, rb, config)


def test_rule_2_can_only_choose_players_that_passed_rule_5(config, pool):
    """The conflict the spec flagged as an open question.

    Rule 5 is applied as a filter over the whole pool first, so when the balance
    guard swaps in a different player it can never resurrect someone the reach
    guard already rejected.
    """
    state = DraftState(settings=config.league)
    give(state, pool, "WR", 2)

    eligible = rules.eligible_players(state, pool, config)
    passed_reach, _ = rules.apply_reach_filter(state, eligible, config)
    allowed = set(passed_reach["player_id"])

    picks = recommend(state, pool, config, limit=10)
    assert picks, "expected recommendations"
    for pick in picks:
        assert pick.player_id in allowed


def test_balance_guard_actually_switches_the_recommendation(config, pool):
    """With 2 WR and 0 RB rostered, a third WR would make it 3-0 and get blocked.

    The guard only has anything to do when the top-scoring player is the one
    that would cause the imbalance, so the fixture is tilted to put a WR on top.
    """
    state = DraftState(settings=config.league)
    give(state, pool, "WR", 2)

    tilted = pool.copy()
    available_wr = tilted[
        (tilted["position"] == "WR") & (~tilted["player_id"].isin(state.drafted_ids))
    ]
    top_wr = available_wr.iloc[0]["player_id"]
    tilted.loc[tilted["player_id"] == top_wr, "ensemble_score"] = 1000.0

    picks = recommend(state, tilted, config, limit=5)

    assert picks[0].position == "RB"
    assert "balance guard" in picks[0].reasons[0].lower()
    assert top_wr not in [p.player_id for p in picks[:1]]


# --------------------------------------------------------------------------
# Rule 6 -- low-value fallback
# --------------------------------------------------------------------------

def test_low_value_pool_falls_back_to_adp(config, pool):
    """When nothing clears the VOR floor, order by ADP instead."""
    state = DraftState(settings=config.league)
    flattened = pool.copy()
    flattened["vor"] = 0.1  # everyone below the 0.5 floor

    picks = recommend(state, flattened, config, limit=5)
    assert "Rule 6" in picks[0].reasons[0]
    assert [p.adp_rank for p in picks] == sorted(p.adp_rank for p in picks)


# --------------------------------------------------------------------------
# Review addendum -- positional drop-off
# --------------------------------------------------------------------------

def test_dropoff_prefers_the_scarcer_position(config, pool):
    """The spec's Kittle-over-Warren case.

    RB and TE are close in VOR now, but TE is projected to fall off a cliff
    before the next pick while FLEX stays deep, so TE should win.
    """
    state = DraftState(settings=LeagueSettings(n_teams=12, my_slot=1))
    state.record(pool.iloc[0])  # burn a pick so we are mid-round

    dropoffs = rules.projected_dropoff(state, pool, config)
    assert set(dropoffs) == {"QB", "FLEX", "TE"}
    for info in dropoffs.values():
        assert 0.0 <= info["dropoff"] <= 1.0


def test_dropoff_bonus_saturates_at_the_threshold(config):
    dropoffs = {"TE": {"best_now": 10.0, "best_later": 5.0, "dropoff": 0.50}}
    bonus = rules.dropoff_bonus("TE", dropoffs, config)
    assert bonus == pytest.approx(config.rules.dropoff_max_bonus)


def test_dropoff_bonus_scales_below_the_threshold(config):
    dropoffs = {"TE": {"best_now": 10.0, "best_later": 8.0, "dropoff": 0.20}}
    bonus = rules.dropoff_bonus("TE", dropoffs, config)
    expected = (0.20 / config.rules.dropoff_threshold) * config.rules.dropoff_max_bonus
    assert bonus == pytest.approx(expected)


def test_no_dropoff_bonus_when_nothing_is_lost(config):
    dropoffs = {"FLEX": {"best_now": 10.0, "best_later": 10.0, "dropoff": 0.0}}
    assert rules.dropoff_bonus("FLEX", dropoffs, config) == 0.0


# --------------------------------------------------------------------------
# Run-heavy RB boost
# --------------------------------------------------------------------------

def test_rush_boost_applies_only_to_run_heavy_rbs(config):
    boosted = pd.Series({"position": "RB", "run_heavy_team": True})
    plain = pd.Series({"position": "RB", "run_heavy_team": False})
    receiver = pd.Series({"position": "WR", "run_heavy_team": True})

    assert rules.rush_boost(boosted, config) == config.rules.rush_boost
    assert rules.rush_boost(plain, config) == 0.0
    assert rules.rush_boost(receiver, config) == 0.0


def test_run_heavy_rb_is_promoted(config, pool):
    """Two RBs of equal value; the one on a run-heavy team should rank higher."""
    state = DraftState(settings=config.league)
    modified = pool.copy()

    rbs = modified[modified["position"] == "RB"].head(2)
    lower, upper = rbs.iloc[1], rbs.iloc[0]
    modified.loc[modified["player_id"] == lower["player_id"], "run_heavy_team"] = True
    modified.loc[modified["player_id"] == lower["player_id"], "ensemble_score"] = (
        upper["ensemble_score"] - 1.0
    )

    picks = recommend(state, modified, config, limit=3)
    assert picks[0].player_id == int(lower["player_id"])
    assert any("rushing volume" in r for r in picks[0].reasons)


def test_balance_guard_overrides_the_rush_boost_with_best_adp_wr(config, pool):
    """When the boosted RB would break balance, take the best-ADP WR instead."""
    state = DraftState(settings=config.league)
    give(state, pool, "RB", 2)

    modified = pool.copy()
    modified.loc[modified["position"] == "RB", "run_heavy_team"] = True

    picks = recommend(state, modified, config, limit=5)
    assert picks[0].position == "WR"

    available_wr = state.available(modified)
    available_wr = available_wr[available_wr["position"] == "WR"]
    assert picks[0].adp_rank == int(available_wr["adp_rank"].min())


def test_team_carries_basis_is_selectable(config):
    other = RuleConfig(rush_rank_basis="team_carries")
    assert other.rush_rank_basis == "team_carries"

    with pytest.raises(ValueError, match="rush_rank_basis"):
        RuleConfig(rush_rank_basis="nonsense")


# --------------------------------------------------------------------------
# Rule 9 -- bye weeks
# --------------------------------------------------------------------------

def test_bye_penalty_fires_on_a_starter_collision(config, pool):
    state = DraftState(settings=config.league)
    give(state, pool, "RB")  # every fixture player has bye week 7

    candidate = state.available(pool)
    candidate = candidate[candidate["position"] == "RB"].iloc[0]
    assert rules.bye_penalty(state, candidate, pool, config) < 0


def test_no_bye_penalty_once_the_position_is_full(config, pool):
    """Bench depth sharing a bye is not a lineup problem."""
    state = DraftState(settings=config.league)
    give(state, pool, "RB", config.league.rb)

    candidate = state.available(pool)
    candidate = candidate[candidate["position"] == "RB"].iloc[0]
    assert rules.bye_penalty(state, candidate, pool, config) == 0.0


def test_no_bye_penalty_for_a_different_week(config, pool):
    state = DraftState(settings=config.league)
    give(state, pool, "RB")

    modified = pool.copy()
    candidate = state.available(modified)
    candidate = candidate[candidate["position"] == "RB"].iloc[0].copy()
    candidate["bye_week"] = 11
    assert rules.bye_penalty(state, candidate, modified, config) == 0.0


# --------------------------------------------------------------------------
# Roster-need guard
# --------------------------------------------------------------------------

def test_empty_roster_needs_every_starting_slot(config, pool):
    state = DraftState(settings=config.league)
    needs = rules.unmet_starting_needs(state, config)

    assert needs.count("QB") == config.league.qb
    assert needs.count("TE") == config.league.te
    assert needs.count("RB") == config.league.rb
    assert needs.count("WR") == config.league.wr
    assert "FLEX" in needs


def test_needs_shrink_as_slots_fill(config, pool):
    state = DraftState(settings=config.league)
    give(state, pool, "QB")
    assert "QB" not in rules.unmet_starting_needs(state, config)


def test_flex_is_satisfied_by_either_position(config, pool):
    """RB/WR/FLEX is three bodies out of RB and WR in any mix."""
    state = DraftState(settings=config.league)
    give(state, pool, "RB", config.league.rb)
    give(state, pool, "WR", config.league.wr)

    needs = rules.unmet_starting_needs(state, config)
    assert needs.count("RB") == 0 and needs.count("WR") == 0
    assert "FLEX" in needs  # the flex body is still owed

    give(state, pool, "WR")
    assert "FLEX" not in rules.unmet_starting_needs(state, config)


def test_needed_positions_expands_flex():
    assert rules.needed_positions(["FLEX"]) == {"RB", "WR"}
    assert rules.needed_positions(["QB", "TE"]) == {"QB", "TE"}


def test_roster_guard_forces_an_unfilled_position_late(small_config, pool):
    """With picks running out, the engine must stop taking best-available.

    The roster here is all RB/WR with no QB, and only one usable pick remains
    before the kicker round, so a quarterback is the only legal choice.
    """
    league = small_config.league
    state = DraftState(settings=league)

    # Fill everything except QB, leaving exactly one pick before the K/DEF rounds.
    my_picks = state.pick_numbers_for_slot(league.my_slot)
    usable = [p for p in my_picks if state.round_of(p) < league.total_rounds - 1]
    give(state, pool, "RB", 3)
    give(state, pool, "WR", 3)
    give(state, pool, "TE", 1)
    fast_forward(state, pool, max(0, usable[-1] - len(state.picks) - 1))

    needs = rules.unmet_starting_needs(state, small_config)
    assert "QB" in needs

    picks = recommend(state, pool, small_config, limit=3)
    assert picks[0].position == "QB"
    assert "Roster guard" in picks[0].reasons[0]


def test_roster_guard_stays_out_of_the_way_early(config, pool):
    """Plenty of picks left means no forcing -- best available wins."""
    state = DraftState(settings=config.league)
    picks = recommend(state, pool, config, limit=1)
    assert not any("Roster guard" in r for r in picks[0].reasons)


def test_balance_guard_still_applies_under_the_rule_6_fallback(config, pool):
    """Rule 2 outranks rule 6, so the ADP fallback must respect roster balance.

    Regression: rule 6 used to return a pure-ADP list directly, skipping the
    balance guard entirely. Over a full draft that let one team drift to 3 RB
    and 8 WR, because every late-round player is below the VOR floor.
    """
    state = DraftState(settings=config.league)
    give(state, pool, "WR", 2)

    flattened = pool.copy()
    flattened["vor"] = 0.1  # everyone under the floor, so rule 6 fires

    # Make sure the best-ADP available player is a WR, which would make it 3-0.
    available = flattened[~flattened["player_id"].isin(state.drafted_ids)]
    top_wr = available[available["position"] == "WR"].sort_values("adp_rank").iloc[0]
    flattened.loc[flattened["player_id"] == top_wr["player_id"], "adp_rank"] = 0

    picks = recommend(state, flattened, config, limit=5)

    assert any("Rule 6" in r for r in picks[0].reasons)
    assert picks[0].position == "RB", "balance guard was skipped in the rule 6 path"
    assert "balance guard" in picks[0].reasons[0].lower()
