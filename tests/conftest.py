"""Synthetic fixtures.

The tests run entirely on hand-built data so the rule logic is verified against
numbers that can be checked by eye, with no network access.
"""

from __future__ import annotations

import pandas as pd
import pytest

from fantasy_vor.config import Config, LeagueSettings, RuleConfig


@pytest.fixture
def league() -> LeagueSettings:
    return LeagueSettings(n_teams=12, my_slot=1, bench=6)


@pytest.fixture
def config(league: LeagueSettings) -> Config:
    return Config(league=league, rules=RuleConfig())


def make_stats(rows: list[tuple[int, str, str, str, float, float]]) -> pd.DataFrame:
    """Build a season-stats frame from (id, name, team, position, games, ppg)."""
    return pd.DataFrame(
        [
            {
                "player_id": pid,
                "name": name,
                "team": team,
                "position": position,
                "games": games,
                "ppg": ppg,
                "ppr_pts": games * ppg,
            }
            for pid, name, team, position, games, ppg in rows
        ]
    )


@pytest.fixture
def stats() -> pd.DataFrame:
    """A pool deep enough to exercise the replacement-rank cutoffs.

    30 RBs and 40 WRs means the pooled RB/WR ranking is 70 deep, comfortably past
    the 60th-ranked flex cutoff for a 12-team league.
    """
    rows: list[tuple[int, str, str, str, float, float]] = []
    pid = 1

    # RBs: 25.0 ppg down to 10.5, in 0.5 steps.
    for i in range(30):
        rows.append((pid, f"RB{i + 1}", "SF", "RB", 17.0, 25.0 - i * 0.5))
        pid += 1

    # WRs: 24.0 ppg down to 4.5, in 0.5 steps.
    for i in range(40):
        rows.append((pid, f"WR{i + 1}", "DAL", "WR", 17.0, 24.0 - i * 0.5))
        pid += 1

    # QBs and TEs: 20 each, so rank 12 exists for both.
    for i in range(20):
        rows.append((pid, f"QB{i + 1}", "BUF", "QB", 17.0, 26.0 - i * 0.5))
        pid += 1
    for i in range(20):
        rows.append((pid, f"TE{i + 1}", "KC", "TE", 17.0, 18.0 - i * 0.5))
        pid += 1

    for i in range(15):
        rows.append((pid, f"K{i + 1}", "NYJ", "K", 17.0, 10.0 - i * 0.2))
        pid += 1
    for i in range(15):
        rows.append((pid, f"DST{i + 1}", "PIT", "DST", 17.0, 9.0 - i * 0.2))
        pid += 1

    return make_stats(rows)


@pytest.fixture
def pool(stats: pd.DataFrame, config: Config) -> pd.DataFrame:
    """A fully scored pool built from the synthetic stats."""
    from fantasy_vor.scoring import ensemble, vor

    scored = vor.compute_vor(stats, config.league, config.rules.min_games)

    # ADP ordering follows VOR here, which keeps the fixtures predictable; the
    # tests that care about ADP/VOR divergence set it explicitly.
    scored = scored.sort_values("vor", ascending=False, ignore_index=True)
    scored["adp_rank"] = range(1, len(scored) + 1)
    scored["adp"] = scored["adp_rank"].astype(float)
    scored["bye_week"] = 7
    scored["run_heavy_team"] = False

    return ensemble.compute_ensemble(scored, config.weights)


def give(state, pool: pd.DataFrame, position: str, count: int = 1) -> None:
    """Put ``count`` players at ``position`` onto *my* roster.

    Rule tests care about roster composition, not about who else picked what, so
    this assigns directly to my slot instead of walking the snake order.
    """
    from fantasy_vor.draft.state import Pick

    available = pool[
        (pool["position"] == position) & (~pool["player_id"].isin(state.drafted_ids))
    ]
    for i in range(count):
        row = available.iloc[i]
        state.picks.append(
            Pick(
                pick_number=len(state.picks) + 1,
                team_slot=state.settings.my_slot,
                player_id=int(row["player_id"]),
                name=str(row["name"]),
                position=position,
            )
        )


@pytest.fixture
def small_league() -> LeagueSettings:
    """A 4-team league, small enough to draft to completion from the fixture pool."""
    return LeagueSettings(n_teams=4, my_slot=1, bench=2)


@pytest.fixture
def small_config(small_league: LeagueSettings) -> Config:
    return Config(league=small_league, rules=RuleConfig())
