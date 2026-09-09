"""Snake ordering and roster bookkeeping."""

from __future__ import annotations

import pytest

from fantasy_vor.config import LeagueSettings
from fantasy_vor.draft.state import DraftState


@pytest.fixture
def state() -> DraftState:
    return DraftState(settings=LeagueSettings(n_teams=12, my_slot=1, bench=6))


def test_odd_rounds_run_forward(state):
    assert [state.slot_on_clock(p) for p in range(1, 13)] == list(range(1, 13))


def test_even_rounds_run_backward(state):
    assert [state.slot_on_clock(p) for p in range(13, 25)] == list(range(12, 0, -1))


def test_round_boundaries(state):
    assert state.round_of(12) == 1
    assert state.round_of(13) == 2
    assert state.round_of(24) == 2
    assert state.round_of(25) == 3


@pytest.mark.parametrize(
    "slot,expected",
    [
        (1, [1, 24, 25, 48]),
        (6, [6, 19, 30, 43]),
        (12, [12, 13, 36, 37]),
    ],
)
def test_pick_numbers_for_slot(slot, expected):
    state = DraftState(settings=LeagueSettings(n_teams=12, my_slot=slot))
    assert state.pick_numbers_for_slot(slot)[:4] == expected


def test_turn_wraps_at_the_end_of_a_round():
    """Slot 12 picks back to back across the 1-2 boundary."""
    state = DraftState(settings=LeagueSettings(n_teams=12, my_slot=12))
    assert state.slot_on_clock(12) == 12
    assert state.slot_on_clock(13) == 12


def test_picks_until_my_next_is_the_gap_to_my_following_pick():
    """Slot 1 has the longest wait; slot 12 the shortest."""
    first = DraftState(settings=LeagueSettings(n_teams=12, my_slot=1))
    assert first.picks_until_my_next() == 23

    last = DraftState(settings=LeagueSettings(n_teams=12, my_slot=12))
    assert last.my_next_pick_after(12) == 13


def test_picks_until_my_next_is_none_at_the_end(state):
    total = state.settings.total_picks
    assert state.my_next_pick_after(total) is None


def test_record_and_undo(state, pool):
    player = pool.iloc[0]
    pick = state.record(player)

    assert pick.pick_number == 1
    assert pick.team_slot == 1
    assert state.current_pick == 2
    assert state.count(pick.position) == 1

    state.undo()
    assert state.current_pick == 1
    assert state.picks == []


def test_cannot_draft_the_same_player_twice(state, pool):
    player = pool.iloc[0]
    state.record(player)
    with pytest.raises(ValueError, match="already been drafted"):
        state.record(player)


def test_available_excludes_drafted(state, pool):
    player = pool.iloc[0]
    state.record(player)
    assert player["player_id"] not in set(state.available(pool)["player_id"])


def test_save_and_load_round_trips(state, pool, tmp_path):
    for i in range(5):
        state.record(pool.iloc[i])

    path = tmp_path / "draft.json"
    state.save(path)
    restored = DraftState.load(path)

    assert restored.settings == state.settings
    assert restored.picks == state.picks
