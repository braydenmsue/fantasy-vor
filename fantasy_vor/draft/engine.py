"""Recommendation engine -- a pure function of (DraftState, pool).

Rule order, following the spec's resolved open questions:

1.  Eligibility  -- drafted players, position caps (rule 3), K/DST gating (rule 4)
2.  Rule 5       -- anti-reach, as a filter over the whole eligible pool
3.  Scoring      -- ensemble plus drop-off bonus, run-heavy RB boost, bye penalty
4.  Rule 2       -- RB/WR balance guard, over the already-filtered pool
5.  Rule 6       -- low-value fallback to ADP
6.  Rules 7-8    -- kicker in the second-to-last round, defense in the last
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import pandas as pd

from ..config import Config
from . import rules
from .state import DraftState

log = logging.getLogger(__name__)


@dataclass
class Recommendation:
    player_id: int
    name: str
    position: str
    team: str
    adp_rank: int
    vor: float
    ensemble_score: float
    adjusted_score: float
    reasons: list[str] = field(default_factory=list)

    def __str__(self) -> str:
        return (
            f"{self.name} ({self.position}, {self.team}) "
            f"VOR {self.vor:+.1f} | ADP {self.adp_rank} | score {self.adjusted_score:.1f}"
        )


def _to_recommendation(row: pd.Series, adjusted: float, reasons: list[str]) -> Recommendation:
    return Recommendation(
        player_id=int(row["player_id"]),
        name=str(row["name"]),
        position=str(row["position"]),
        team=str(row["team"]),
        adp_rank=int(row["adp_rank"]),
        vor=float(row["vor"]),
        ensemble_score=float(row["ensemble_score"]),
        adjusted_score=adjusted,
        reasons=reasons,
    )


def _by_adp(players: pd.DataFrame, reason: str, limit: int) -> list[Recommendation]:
    ordered = players.sort_values("adp_rank").head(limit)
    return [
        _to_recommendation(row, -float(row["adp_rank"]), [reason])
        for _, row in ordered.iterrows()
    ]


def _apply_balance_guard(
    state: DraftState,
    candidates: pd.DataFrame,
    config: Config,
    ordered: list[Recommendation],
    by_adp: bool = False,
) -> list[Recommendation]:
    """Rule 2, applied to an already-ordered candidate list.

    If the leading candidate would push RB and WR too far apart, promote the best
    player at whichever position is short. Ranking within that position is by VOR
    normally, but by ADP when rule 6 is in force -- there VOR carries no signal.

    Only ever reorders ``ordered``, so it cannot resurrect a player that the
    reach filter already removed.
    """
    if not ordered:
        return ordered

    top = ordered[0]
    matching = candidates[candidates["player_id"] == top.player_id]
    if matching.empty:
        return ordered

    top_row = matching.iloc[0]
    if not rules.violates_balance(state, top_row, config):
        return ordered

    wanted = rules.short_position(state)
    replacements = [r for r in ordered if r.position == wanted]
    if not replacements:
        # Nothing at the short position survived the earlier filters, so the
        # guard has nothing to swap in and steps aside.
        return ordered

    rb, wr = state.count("RB"), state.count("WR")
    if by_adp:
        replacements.sort(key=lambda r: r.adp_rank)
        note = (
            f"Rule 2 balance guard: RB {rb} vs WR {wr}, "
            f"taking the best-ADP {wanted} instead of {top.name}"
        )
    elif wanted == "WR" and top.position == "RB" and bool(top_row.get("run_heavy_team", False)):
        # The run-heavy RB boost defers to balance: take the best-ADP WR instead.
        replacements.sort(key=lambda r: r.adp_rank)
        note = (
            f"Rule 2 blocks the run-heavy RB boost (RB {rb} vs WR {wr}); "
            f"best-ADP WR instead"
        )
    else:
        replacements.sort(key=lambda r: r.vor, reverse=True)
        note = (
            f"Rule 2 balance guard: RB {rb} vs WR {wr}, "
            f"taking the best {wanted} instead of {top.name}"
        )

    chosen = replacements[0]
    chosen.reasons.insert(0, note)
    return [chosen] + [r for r in ordered if r.player_id != chosen.player_id]


def recommend(
    state: DraftState, pool: pd.DataFrame, config: Config, limit: int = 5
) -> list[Recommendation]:
    """Ranked recommendations for the pick currently on the clock."""
    league = config.league
    eligible = rules.eligible_players(state, pool, config)
    if eligible.empty:
        return []

    # Rules 7-8: the end of the draft is reserved for K and DST.
    last_round = league.total_rounds
    if state.current_round == last_round - 1:
        kickers = eligible[eligible["position"] == "K"]
        if not kickers.empty:
            return _by_adp(kickers, "Rule 7: second-to-last round, best-ADP kicker", limit)
    if state.current_round == last_round:
        defenses = eligible[eligible["position"] == "DST"]
        if not defenses.empty:
            return _by_adp(defenses, "Rule 8: last round, best-ADP defense", limit)

    # Rule 5 first, as a filter over the entire eligible pool, so that nothing
    # downstream can resurrect a player the reach guard rejected.
    candidates, relaxed = rules.apply_reach_filter(state, eligible, config)
    reach_note = (
        "Rule 5 relaxed: every remaining player is past their ADP" if relaxed else None
    )

    # Roster guard: if the picks left before the K/DEF rounds have run down to
    # the number of starting slots still open, stop taking best-available and
    # fill them. Without this the engine drafts rosters it cannot legally start.
    needs = rules.unmet_starting_needs(state, config)
    remaining = rules.picks_before_endgame(state, config)
    forced_note = None
    if needs and len(needs) >= remaining > 0:
        wanted = rules.needed_positions(needs)
        forced = candidates[candidates["position"].isin(wanted)]
        if forced.empty:
            # Filling the lineup outranks the anti-reach discipline.
            forced = eligible[eligible["position"].isin(wanted)]
        if not forced.empty:
            candidates = forced
            forced_note = (
                f"Roster guard: {remaining} picks left before the K/DEF rounds and "
                f"{len(needs)} starting slots still open ({', '.join(needs)})"
            )

    # Rule 6: if nothing left has real value, stop pretending VOR means anything.
    # The balance guard still applies -- rule 2 sits above rule 6 in the spec's
    # priority order, so falling back to ADP must not also abandon roster shape.
    if float(candidates["vor"].max()) < config.rules.low_vor_floor:
        fallback = _by_adp(
            candidates,
            f"Rule 6: no player above {config.rules.low_vor_floor} VOR, drafting by ADP",
            len(candidates),
        )
        guarded = _apply_balance_guard(state, candidates, config, fallback, by_adp=True)
        return guarded[:limit]

    # The drop-off projection deliberately runs on the full eligible pool rather
    # than the reach-filtered candidates: it asks who will still be on the board
    # at my next pick, and those are by definition players with later ADP -- the
    # exact ones the reach filter removes.
    dropoffs = rules.projected_dropoff(state, eligible, config)
    gap = state.picks_until_my_next()

    scored: list[Recommendation] = []
    for _, row in candidates.iterrows():
        reasons: list[str] = []
        if forced_note:
            reasons.append(forced_note)
        if reach_note:
            reasons.append(reach_note)

        adjusted = float(row["ensemble_score"])

        group = rules.position_group(str(row["position"]))
        if group:
            bonus = rules.dropoff_bonus(group, dropoffs, config)
            if bonus > 0.1:
                info = dropoffs[group]
                reasons.append(
                    f"{group} projected to lose {info['dropoff']:.0%} of its best VOR "
                    f"({info['best_now']:.1f} -> {info['best_later']:.1f}) "
                    f"before your next pick in {gap} picks (+{bonus:.1f})"
                )
                adjusted += bonus

        boost = rules.rush_boost(row, config)
        if boost:
            reasons.append(
                f"{row['team']} is top-{config.rules.rush_rank_top_n} in rushing volume (+{boost:.1f})"
            )
            adjusted += boost

        penalty = rules.bye_penalty(state, row, pool, config)
        if penalty:
            reasons.append(
                f"bye week {int(row['bye_week'])} collides with a projected "
                f"{row['position']} starter ({penalty:.1f})"
            )
            adjusted += penalty

        if bool(row.get("vor_imputed", False)):
            reasons.append("VOR imputed from ADP (no usable prior season)")

        scored.append(_to_recommendation(row, adjusted, reasons))

    scored.sort(key=lambda r: r.adjusted_score, reverse=True)

    # Rule 2: the balance guard, applied to the already-filtered candidates.
    scored = _apply_balance_guard(state, candidates, config, scored)

    return scored[:limit]
