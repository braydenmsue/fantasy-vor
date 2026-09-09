"""Interactive draft REPL.

Designed for a live draft clock: short commands, fuzzy name matching, and every
recommendation carries the reasons the rules fired.

    rec [n]        top n recommendations for whoever is on the clock
    pick <name>    record a pick for the team on the clock
    undo           take back the last pick
    roster [slot]  show a roster (defaults to yours)
    board [pos]    best available, optionally filtered by position
    who            who is on the clock
    save/load      persist the draft to JSON
    help / quit
"""

from __future__ import annotations

import argparse
import difflib
import logging
import sys

import pandas as pd

from .config import Config, EnsembleWeights, LeagueSettings, RuleConfig
from .draft.engine import recommend
from .draft.state import DraftState
from .pool import build_pool

log = logging.getLogger(__name__)

DEFAULT_SAVE = "draft.json"


def find_player(pool: pd.DataFrame, query: str) -> pd.Series | None:
    """Resolve a typed name to a player, tolerating partial and misspelled input."""
    query = query.strip().lower()
    if not query:
        return None

    names = pool["name"].str.lower()

    exact = pool[names == query]
    if len(exact) == 1:
        return exact.iloc[0]

    contains = pool[names.str.contains(query, regex=False)]
    if len(contains) == 1:
        return contains.iloc[0]
    if len(contains) > 1:
        # Prefer the earliest ADP among the matches -- during a draft the player
        # you mean is almost always the more valuable one.
        return contains.sort_values("adp_rank").iloc[0]

    close = difflib.get_close_matches(query, names.tolist(), n=1, cutoff=0.7)
    if close:
        return pool[names == close[0]].iloc[0]
    return None


def print_recommendations(state: DraftState, pool: pd.DataFrame, config: Config, limit: int) -> None:
    picks = recommend(state, pool, config, limit=limit)
    if not picks:
        print("  no eligible players")
        return

    gap = state.picks_until_my_next()
    header = f"Pick {state.current_pick} (round {state.current_round}, slot {state.slot_on_clock(state.current_pick)})"
    if gap:
        header += f" -- your next pick is {gap} picks away"
    print(f"\n{header}\n")

    for i, rec in enumerate(picks, 1):
        marker = ">>" if i == 1 else "  "
        print(f"{marker} {i}. {rec}")
        for reason in rec.reasons:
            print(f"       - {reason}")
    print()


def print_roster(state: DraftState, slot: int) -> None:
    roster = state.roster(slot)
    label = "your roster" if slot == state.settings.my_slot else f"slot {slot}"
    if not roster:
        print(f"  {label}: empty")
        return
    print(f"\n  {label}:")
    for pick in roster:
        print(f"    R{state.round_of(pick.pick_number):<2} {pick.position:<4} {pick.name}")
    counts = ", ".join(f"{k} {v}" for k, v in sorted(state.position_counts(slot).items()))
    print(f"    ({counts})\n")


def print_board(state: DraftState, pool: pd.DataFrame, position: str | None, limit: int) -> None:
    available = state.available(pool)
    if position:
        available = available[available["position"] == position.upper()]
    if available.empty:
        print("  nothing available")
        return

    print()
    for _, row in available.head(limit).iterrows():
        flag = "*" if row["vor_imputed"] else " "
        print(
            f"  {row['name']:<24} {row['position']:<4} {row['team']:<4} "
            f"ADP {int(row['adp_rank']):>3}  VOR {float(row['vor']):+6.1f}{flag}  "
            f"score {row['ensemble_score']:.1f}"
        )
    print()


def repl(state: DraftState, pool: pd.DataFrame, config: Config) -> None:
    print(
        f"\nFantasy VOR draft assistant -- {config.league.n_teams} teams, "
        f"slot {config.league.my_slot}, {config.league.total_rounds} rounds"
    )
    print(f"{len(pool)} players loaded. Type 'help' for commands.\n")
    print_recommendations(state, pool, config, 5)

    while True:
        try:
            raw = input("draft> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return

        if not raw:
            continue
        command, _, argument = raw.partition(" ")
        command = command.lower()
        argument = argument.strip()

        if command in ("quit", "exit", "q"):
            return

        if command in ("help", "?"):
            print(__doc__)

        elif command in ("rec", "r"):
            limit = int(argument) if argument.isdigit() else 5
            print_recommendations(state, pool, config, limit)

        elif command in ("pick", "p"):
            player = find_player(state.available(pool), argument)
            if player is None:
                print(f"  no available player matching {argument!r}")
                continue
            pick = state.record(player)
            mine = " <-- yours" if pick.team_slot == config.league.my_slot else ""
            print(f"  {pick.pick_number}. slot {pick.team_slot}: {pick.name} ({pick.position}){mine}")
            if state.is_complete:
                print("\n  draft complete")
                print_roster(state, config.league.my_slot)
            elif state.is_my_turn:
                print_recommendations(state, pool, config, 5)

        elif command in ("undo", "u"):
            pick = state.undo()
            print(f"  undid {pick.name}" if pick else "  nothing to undo")

        elif command == "roster":
            print_roster(state, int(argument) if argument.isdigit() else config.league.my_slot)

        elif command in ("board", "b"):
            print_board(state, pool, argument or None, 15)

        elif command == "who":
            slot = state.slot_on_clock(state.current_pick)
            mine = " (you)" if slot == config.league.my_slot else ""
            print(f"  pick {state.current_pick}, round {state.current_round}, slot {slot}{mine}")

        elif command == "save":
            path = argument or DEFAULT_SAVE
            state.save(path)
            print(f"  saved to {path}")

        else:
            print(f"  unknown command {command!r} -- try 'help'")


def build_config(args: argparse.Namespace) -> Config:
    return Config(
        league=LeagueSettings(
            n_teams=args.teams,
            my_slot=args.slot,
            stats_year=args.stats_year,
            adp_year=args.adp_year,
        ),
        weights=EnsembleWeights(),
        rules=RuleConfig(rush_rank_basis=args.rush_basis),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="VOR-based fantasy draft assistant")
    parser.add_argument("--teams", type=int, default=12)
    parser.add_argument("--slot", type=int, default=1, help="your draft slot, 1-indexed")
    parser.add_argument("--stats-year", type=int, default=2025)
    parser.add_argument("--adp-year", type=int, default=2026)
    parser.add_argument(
        "--rush-basis",
        choices=("rb_carries", "team_carries"),
        default="rb_carries",
        help="basis for the run-heavy team boost",
    )
    parser.add_argument("--refresh", action="store_true", help="re-fetch all sources")
    parser.add_argument("--weekly", action="store_true", help="also pull weekly logs (slow)")
    parser.add_argument("--load", metavar="PATH", help="resume a saved draft")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(message)s",
    )

    config = build_config(args)
    if not 1 <= config.league.my_slot <= config.league.n_teams:
        parser.error(f"--slot must be between 1 and {config.league.n_teams}")

    pool = build_pool(config, refresh=args.refresh, weekly=args.weekly)
    state = DraftState.load(args.load) if args.load else DraftState(settings=config.league)

    repl(state, pool, config)
    return 0


if __name__ == "__main__":
    sys.exit(main())
