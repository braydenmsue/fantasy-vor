"""Draft state and snake-order arithmetic.

``DraftState`` is deliberately a plain record of what has happened. The
recommendation engine is a pure function of ``(DraftState, pool)``, which is what
makes it replayable against a past draft.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from pathlib import Path

import pandas as pd

from ..config import LeagueSettings


@dataclass(frozen=True)
class Pick:
    pick_number: int  # 1-indexed overall
    team_slot: int  # 1-indexed draft slot
    player_id: int
    name: str
    position: str


@dataclass
class DraftState:
    settings: LeagueSettings
    picks: list[Pick] = field(default_factory=list)

    # ---- snake ordering -------------------------------------------------

    @property
    def current_pick(self) -> int:
        """1-indexed overall pick number that is on the clock."""
        return len(self.picks) + 1

    def round_of(self, pick_number: int) -> int:
        return (pick_number - 1) // self.settings.n_teams + 1

    def slot_on_clock(self, pick_number: int) -> int:
        """Which draft slot owns ``pick_number`` under snake ordering."""
        n = self.settings.n_teams
        index = (pick_number - 1) % n
        if self.round_of(pick_number) % 2 == 1:
            return index + 1
        return n - index

    def pick_numbers_for_slot(self, slot: int) -> list[int]:
        return [
            p
            for p in range(1, self.settings.total_picks + 1)
            if self.slot_on_clock(p) == slot
        ]

    def my_next_pick_after(self, pick_number: int) -> int | None:
        """My next pick strictly after ``pick_number``, or None if the draft ends."""
        for p in self.pick_numbers_for_slot(self.settings.my_slot):
            if p > pick_number:
                return p
        return None

    def picks_until_my_next(self) -> int | None:
        """How many picks elapse between the current pick and my following one.

        This is the window the drop-off projection looks across.
        """
        nxt = self.my_next_pick_after(self.current_pick)
        if nxt is None:
            return None
        return nxt - self.current_pick

    @property
    def is_my_turn(self) -> bool:
        return self.slot_on_clock(self.current_pick) == self.settings.my_slot

    @property
    def current_round(self) -> int:
        return self.round_of(self.current_pick)

    @property
    def is_complete(self) -> bool:
        return len(self.picks) >= self.settings.total_picks

    # ---- roster bookkeeping ---------------------------------------------

    def roster(self, slot: int | None = None) -> list[Pick]:
        slot = self.settings.my_slot if slot is None else slot
        return [p for p in self.picks if p.team_slot == slot]

    def position_counts(self, slot: int | None = None) -> dict[str, int]:
        counts: dict[str, int] = {}
        for pick in self.roster(slot):
            counts[pick.position] = counts.get(pick.position, 0) + 1
        return counts

    def count(self, position: str, slot: int | None = None) -> int:
        return self.position_counts(slot).get(position, 0)

    @property
    def drafted_ids(self) -> set[int]:
        return {p.player_id for p in self.picks}

    def available(self, pool: pd.DataFrame) -> pd.DataFrame:
        return pool[~pool["player_id"].isin(self.drafted_ids)]

    # ---- mutation --------------------------------------------------------

    def record(self, player: pd.Series) -> Pick:
        """Append the pick currently on the clock."""
        if self.is_complete:
            raise ValueError("the draft is already complete")
        if int(player["player_id"]) in self.drafted_ids:
            raise ValueError(f"{player['name']} has already been drafted")

        pick = Pick(
            pick_number=self.current_pick,
            team_slot=self.slot_on_clock(self.current_pick),
            player_id=int(player["player_id"]),
            name=str(player["name"]),
            position=str(player["position"]),
        )
        self.picks.append(pick)
        return pick

    def undo(self) -> Pick | None:
        return self.picks.pop() if self.picks else None

    # ---- persistence -----------------------------------------------------

    def save(self, path: str | Path) -> None:
        payload = {
            "settings": asdict(self.settings),
            "picks": [asdict(p) for p in self.picks],
        }
        Path(path).write_text(json.dumps(payload, indent=2))

    @classmethod
    def load(cls, path: str | Path) -> "DraftState":
        payload = json.loads(Path(path).read_text())
        return cls(
            settings=LeagueSettings(**payload["settings"]),
            picks=[Pick(**p) for p in payload["picks"]],
        )
