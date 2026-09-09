"""Assemble the draftable player pool from all sources.

This is the single entry point that turns raw sources into the scored frame the
draft engine consumes. Everything downstream of here is pure computation.
"""

from __future__ import annotations

import logging

import pandas as pd

from .config import Config
from .scoring import consistency, ensemble, imputation, vor
from .sources import cache, fantasypros_adp, fantasypros_stats, nflverse

log = logging.getLogger(__name__)


def load_sources(
    config: Config, refresh: bool = False, weekly: bool = False
) -> dict[str, pd.DataFrame]:
    """Fetch (or read from cache) every raw input."""
    league = config.league

    frames = {
        "stats": cache.cached(
            f"stats_{league.stats_year}",
            lambda: fantasypros_stats.fetch_season_stats(league.stats_year),
            refresh,
        ),
        "adp": cache.cached(
            f"adp_{league.adp_year}",
            lambda: fantasypros_adp.fetch_adp(league.adp_year),
            refresh,
        ),
        "rush": cache.cached(
            f"rush_{league.stats_year}",
            lambda: nflverse.fetch_rush_ranks(league.stats_year),
            refresh,
        ),
    }

    if weekly:
        frames["weekly"] = cache.cached(
            f"weekly_{league.stats_year}",
            lambda: fantasypros_stats.fetch_weekly_stats(league.stats_year),
            refresh,
        )

    return frames


def build_pool(
    config: Config, refresh: bool = False, weekly: bool = False
) -> pd.DataFrame:
    """The scored, draftable player pool.

    ADP is the spine: a player who is not in the ADP feed is not being drafted,
    and a player without prior-season stats still needs a row so imputation can
    give them a value.
    """
    frames = load_sources(config, refresh=refresh, weekly=weekly)
    league, rules = config.league, config.rules

    scored_stats = vor.compute_vor(frames["stats"], league, rules.min_games)

    # A handful of dual-eligible players (fullbacks, gadget players) appear on
    # two position pages and so arrive with two rows. Keep the row from the
    # position where they actually produced; the ADP feed is authoritative for
    # what position they are drafted at.
    scored_stats = (
        scored_stats.sort_values("ppr_pts", ascending=False)
        .drop_duplicates("player_id", keep="first")
    )

    pool = frames["adp"].merge(
        scored_stats[
            ["player_id", "games", "ppr_pts", "ppg", "replacement_ppg", "vor", "vor_imputed"]
        ],
        on="player_id",
        how="left",
    )
    pool["vor_imputed"] = pool["vor_imputed"].fillna(False)
    pool["games"] = pool["games"].fillna(0.0)

    if weekly and "weekly" in frames:
        pool = pool.merge(consistency.compute_consistency(frames["weekly"]), on="player_id", how="left")

    pool = imputation.impute_missing_vor(pool)
    pool = ensemble.compute_ensemble(pool, config.weights)

    # Attach run-heavy team flags for the RB boost rule.
    run_heavy = nflverse.run_heavy_teams(
        frames["rush"], rules.rush_rank_top_n, rules.rush_rank_basis
    )
    pool["run_heavy_team"] = pool["team"].isin(run_heavy)

    log.info(
        "pool: %d players, %d with imputed VOR, %d on run-heavy teams",
        len(pool),
        int(pool["vor_imputed"].sum()),
        int(pool["run_heavy_team"].sum()),
    )
    return pool
