"""Score 3 -- weekly consistency (spec section 3).

Computed and stored, but weighted zero in v1: the spec wants this tracked until
there is enough data behind it to trust as a draft input.

Two measures come out of the weekly log:

``consistency``
    ``1 - stdev(weekly) / mean(weekly)``, i.e. one minus the coefficient of
    variation. Higher means a steadier week-to-week producer.

``floor_ppg``
    The 25th-percentile week, which is the spec's alternative framing of the
    same idea and is easier to reason about during a draft.
"""

from __future__ import annotations

import logging

import pandas as pd

log = logging.getLogger(__name__)

MIN_WEEKS = 4


def compute_consistency(weekly: pd.DataFrame) -> pd.DataFrame:
    """Per-player consistency from a weekly point log.

    Expects ``player_id, season, week, ppr_pts``. Returns ``player_id,
    weeks_played, consistency, floor_ppg``.
    """
    if weekly.empty:
        return pd.DataFrame(
            columns=["player_id", "weeks_played", "consistency", "floor_ppg"]
        )

    # A missing week is a bye or an inactive, not a zero-point performance;
    # including those as zeros would punish availability twice, since Score 2
    # already handles games played.
    played = weekly[weekly["ppr_pts"] != 0]

    grouped = played.groupby("player_id")["ppr_pts"]
    frame = pd.DataFrame(
        {
            "weeks_played": grouped.size(),
            "mean_pts": grouped.mean(),
            "std_pts": grouped.std(ddof=0),
            "floor_ppg": grouped.quantile(0.25),
        }
    ).reset_index()

    thin = frame["weeks_played"] < MIN_WEEKS
    frame["consistency"] = 1.0 - (frame["std_pts"] / frame["mean_pts"])
    frame.loc[thin | (frame["mean_pts"] <= 0), "consistency"] = pd.NA
    frame["consistency"] = frame["consistency"].astype("Float64")

    log.info(
        "consistency computed for %d players (%d too thin)",
        int((~thin).sum()),
        int(thin.sum()),
    )
    return frame[["player_id", "weeks_played", "consistency", "floor_ppg"]]
