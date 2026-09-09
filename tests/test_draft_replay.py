"""End-to-end: run a whole draft through the engine and check the result is legal.

This is the test that would catch a rule interaction that only shows up over a
full draft -- a position that never gets filled, a kicker taken in round 3, the
engine running out of eligible players.
"""

from __future__ import annotations

import pytest

from fantasy_vor.config import Config, LeagueSettings, RuleConfig
from fantasy_vor.draft.engine import recommend
from fantasy_vor.draft.state import DraftState


def run_draft(config: Config, pool) -> DraftState:
    """Every team drafts using the engine, so the whole board is engine-driven."""
    state = DraftState(settings=config.league)

    while not state.is_complete:
        slot = state.slot_on_clock(state.current_pick)

        # Recommend from the perspective of whoever is on the clock. Roster
        # lookups key off ``settings.my_slot``, so the state itself has to be
        # re-seated -- the picks list is shared, so this is a view, not a copy.
        seat_league = LeagueSettings(**{**config.league.__dict__, "my_slot": slot})
        seat = Config(league=seat_league, weights=config.weights, rules=config.rules)
        seat_state = DraftState(settings=seat_league, picks=state.picks)

        picks = recommend(seat_state, pool, seat, limit=1)
        assert picks, f"no recommendation at pick {state.current_pick}"

        player = pool[pool["player_id"] == picks[0].player_id].iloc[0]
        seat_state.record(player)

    return state


@pytest.fixture
def completed(small_config, pool) -> DraftState:
    return run_draft(small_config, pool)


def test_draft_completes(completed, small_config):
    assert len(completed.picks) == small_config.league.total_picks


def test_no_player_drafted_twice(completed):
    ids = [p.player_id for p in completed.picks]
    assert len(ids) == len(set(ids))


def test_every_team_fills_its_starting_lineup(completed, small_config):
    """The point of the whole exercise: a legal, startable roster."""
    league = small_config.league

    for slot in range(1, league.n_teams + 1):
        counts = completed.position_counts(slot)

        assert counts.get("QB", 0) >= league.qb, f"slot {slot} has no QB"
        assert counts.get("TE", 0) >= league.te, f"slot {slot} has no TE"
        assert counts.get("K", 0) >= league.k, f"slot {slot} has no kicker"
        assert counts.get("DST", 0) >= league.dst, f"slot {slot} has no defense"

        flex_capable = counts.get("RB", 0) + counts.get("WR", 0)
        assert flex_capable >= league.rb + league.wr + league.flex, (
            f"slot {slot} cannot fill RB/WR/FLEX: {counts}"
        )


def test_position_caps_are_respected(completed, small_config):
    """This bot only supports 1QB / 1TE leagues, so nobody may end up with two."""
    for slot in range(1, small_config.league.n_teams + 1):
        counts = completed.position_counts(slot)
        assert counts.get("QB", 0) <= small_config.rules.max_qb
        assert counts.get("TE", 0) <= small_config.rules.max_te
        assert counts.get("K", 0) <= small_config.league.k
        assert counts.get("DST", 0) <= small_config.league.dst


def test_kickers_and_defenses_only_go_at_the_end(completed, small_config):
    """Rule 4: nothing before the last two rounds."""
    cutoff = small_config.league.total_rounds - 1

    for pick in completed.picks:
        if pick.position in ("K", "DST"):
            assert completed.round_of(pick.pick_number) >= cutoff, (
                f"{pick.name} ({pick.position}) went in round "
                f"{completed.round_of(pick.pick_number)}"
            )


def test_rb_wr_stay_balanced(completed, small_config):
    """Rule 2 should hold for every team over the whole draft."""
    for slot in range(1, small_config.league.n_teams + 1):
        counts = completed.position_counts(slot)
        gap = abs(counts.get("WR", 0) - counts.get("RB", 0))
        assert gap < small_config.rules.rb_wr_imbalance + 1, (
            f"slot {slot} finished {counts}"
        )


def test_replay_is_deterministic(small_config, pool):
    """Same state and pool must give the same recommendation every time."""
    first = run_draft(small_config, pool)
    second = run_draft(small_config, pool)
    assert [p.player_id for p in first.picks] == [p.player_id for p in second.picks]
