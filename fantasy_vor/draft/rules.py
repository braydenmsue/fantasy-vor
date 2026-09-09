"""The draft recommendation rules (spec section 4 plus the Review addendum).

Ordering, as resolved in the spec's open questions:

* Rule 5 (anti-reach) is applied as a **filter over the entire eligible pool
  first**, so rules 1-3 only ever see players that already pass it. This is what
  resolves the rule-2/rule-5 conflict -- the balance guard can no longer pick
  someone the reach guard would then reject.
* K and DST are excluded from rules 1-5 entirely and appear only in the
  last-two-rounds rules.

Each function returns both a result and a human-readable reason, so the CLI can
explain *why* a player is being recommended rather than just naming one.
"""

from __future__ import annotations

import logging

import pandas as pd

from ..config import FLEX_POSITIONS, Config
from .state import DraftState

log = logging.getLogger(__name__)

# The Review section groups positions this way for drop-off purposes: RB and WR
# are one interchangeable FLEX group, QB and TE stand alone.
DROPOFF_GROUPS = {"QB": "QB", "TE": "TE", "RB": "FLEX", "WR": "FLEX"}


def position_group(position: str) -> str | None:
    return DROPOFF_GROUPS.get(position)


# --------------------------------------------------------------------------
# Rules 3, 4 -- eligibility
# --------------------------------------------------------------------------

def eligible_players(
    state: DraftState, pool: pd.DataFrame, config: Config
) -> pd.DataFrame:
    """Undrafted players this team is still allowed to take.

    Rule 3: once a QB (or TE) is rostered, remaining ones are removed.
    Rule 4: K and DST are unavailable outside the last two rounds.
    """
    available = state.available(pool)
    rules, league = config.rules, config.league

    if state.count("QB") >= rules.max_qb:
        available = available[available["position"] != "QB"]
    if state.count("TE") >= rules.max_te:
        available = available[available["position"] != "TE"]

    kicker_round = league.total_rounds - 1
    if state.current_round < kicker_round:
        available = available[~available["position"].isin(["K", "DST"])]

    # Never take a second kicker or defense.
    if state.count("K") >= league.k:
        available = available[available["position"] != "K"]
    if state.count("DST") >= league.dst:
        available = available[available["position"] != "DST"]

    return available


# --------------------------------------------------------------------------
# Rule 5 -- anti-reach, applied as a pool filter
# --------------------------------------------------------------------------

def apply_reach_filter(
    state: DraftState, players: pd.DataFrame, config: Config
) -> tuple[pd.DataFrame, bool]:
    """Drop players whose ADP is more than ``reach_threshold`` picks away.

    Returns the filtered frame and whether the filter had to be relaxed because
    it would otherwise have emptied the pool (late in a draft every remaining
    player's ADP has long since passed).
    """
    threshold = config.rules.reach_threshold
    reach = players["adp_rank"] - state.current_pick
    filtered = players[reach <= threshold]

    if filtered.empty:
        return players, True
    return filtered, False


# --------------------------------------------------------------------------
# Review addendum -- positional VOR drop-off
# --------------------------------------------------------------------------

def projected_dropoff(
    state: DraftState, players: pd.DataFrame, config: Config
) -> dict[str, dict[str, float]]:
    """Expected VOR loss per position group before my next pick.

    Players are assumed to come off the board in ADP order, so anyone whose ADP
    rank falls inside the gap before my next pick is projected gone. The
    remaining best VOR in each group is compared against the best available now.
    """
    gap = state.picks_until_my_next()
    result: dict[str, dict[str, float]] = {}
    if gap is None:
        return result

    next_pick = state.current_pick + gap
    # A player is projected to survive if the market is not expected to take
    # them before my next pick comes around.
    survivors = players[players["adp_rank"] >= next_pick]

    for group in ("QB", "FLEX", "TE"):
        positions = FLEX_POSITIONS if group == "FLEX" else (group,)
        now = players[players["position"].isin(positions)]
        later = survivors[survivors["position"].isin(positions)]

        best_now = float(now["vor"].max()) if not now.empty else 0.0
        best_later = float(later["vor"].max()) if not later.empty else 0.0

        if best_now > 0:
            fraction = max(0.0, (best_now - best_later) / best_now)
        else:
            fraction = 0.0

        result[group] = {
            "best_now": best_now,
            "best_later": best_later,
            "dropoff": fraction,
        }

    return result


def dropoff_bonus(group: str, dropoffs: dict[str, dict[str, float]], config: Config) -> float:
    """Scarcity bonus for a position group, scaled by its projected drop-off.

    The spec's 40% threshold is where the bonus reaches full strength -- at that
    point the position is losing so much value before the next pick that it
    should outweigh a small VOR deficit.
    """
    info = dropoffs.get(group)
    if not info:
        return 0.0
    rules = config.rules
    scale = min(1.0, info["dropoff"] / rules.dropoff_threshold)
    return scale * rules.dropoff_max_bonus


# --------------------------------------------------------------------------
# Run-heavy team RB boost
# --------------------------------------------------------------------------

def rush_boost(player: pd.Series, config: Config) -> float:
    """Boost RBs whose team ranks top-N in rushing volume.

    See ``sources/nflverse.py`` for why the default basis is RB carries rather
    than total team rushing attempts.
    """
    if player["position"] != "RB" or not bool(player.get("run_heavy_team", False)):
        return 0.0
    return config.rules.rush_boost


# --------------------------------------------------------------------------
# Rule 9 -- bye week collisions
# --------------------------------------------------------------------------

def bye_penalty(
    state: DraftState, player: pd.Series, pool: pd.DataFrame, config: Config
) -> float:
    """Penalize stacking projected starters at one position on one bye week.

    Only applies while a position is still filling its starting slots -- once
    you are drafting bench depth, a shared bye is no longer a lineup problem.
    """
    position = str(player["position"])
    bye = int(player.get("bye_week") or 0)
    if not bye or position not in ("QB", "RB", "WR", "TE"):
        return 0.0

    starting_slots = config.league.starting_slots(position)
    if state.count(position) >= starting_slots:
        return 0.0

    by_id = pool.set_index("player_id")
    same_bye = 0
    for pick in state.roster():
        if pick.position != position:
            continue
        if pick.player_id in by_id.index:
            if int(by_id.loc[pick.player_id, "bye_week"] or 0) == bye:
                same_bye += 1

    return -config.rules.bye_penalty if same_bye >= 1 else 0.0


# --------------------------------------------------------------------------
# Rule 2 -- RB/WR balance guard
# --------------------------------------------------------------------------

def violates_balance(state: DraftState, player: pd.Series, config: Config) -> bool:
    """Would taking this player push RB and WR counts too far apart?"""
    position = str(player["position"])
    if position not in FLEX_POSITIONS:
        return False

    rb = state.count("RB")
    wr = state.count("WR")
    if position == "RB":
        rb += 1
    else:
        wr += 1

    return abs(wr - rb) >= config.rules.rb_wr_imbalance


def short_position(state: DraftState) -> str:
    """Whichever of RB/WR this roster has fewer of."""
    return "RB" if state.count("RB") <= state.count("WR") else "WR"


# --------------------------------------------------------------------------
# Roster-need guard
# --------------------------------------------------------------------------
#
# The spec's rules never actually require a legal starting lineup, and pure VOR
# will not produce one on its own: in a 12-team league the QB baseline is QB12,
# so quarterbacks carry low VOR by construction and the engine happily takes
# RB/WR every round. Left alone it drafts teams that cannot field a starter at
# QB or TE. This guard generalizes what rules 7-8 already do for K and DEF --
# reserve just enough picks at the end to fill what is still missing.


def unmet_starting_needs(state: DraftState, config: Config) -> list[str]:
    """Starting slots this roster still cannot fill, one entry per open slot."""
    league = config.league
    needs: list[str] = []

    if state.count("QB") < league.qb:
        needs.append("QB")
    if state.count("TE") < league.te:
        needs.append("TE")

    rb, wr = state.count("RB"), state.count("WR")
    needs.extend(["RB"] * max(0, league.rb - rb))
    needs.extend(["WR"] * max(0, league.wr - wr))

    # The FLEX slot can be filled by either, so it only counts as a need once
    # the dedicated RB and WR slots are accounted for.
    flex_short = (league.rb + league.wr + league.flex) - (rb + wr)
    if flex_short > max(0, league.rb - rb) + max(0, league.wr - wr):
        needs.append("FLEX")

    return needs


def picks_before_endgame(state: DraftState, config: Config) -> int:
    """How many picks this team has left before the rounds reserved for K/DEF."""
    league = config.league
    kicker_round = league.total_rounds - 1
    return sum(
        1
        for p in state.pick_numbers_for_slot(league.my_slot)
        if p >= state.current_pick and state.round_of(p) < kicker_round
    )


def needed_positions(needs: list[str]) -> set[str]:
    """Expand a needs list into the concrete positions that satisfy it."""
    positions: set[str] = set()
    for need in needs:
        if need == "FLEX":
            positions.update(FLEX_POSITIONS)
        else:
            positions.add(need)
    return positions
