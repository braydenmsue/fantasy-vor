"""VOR for players with no usable prior season.

Rookies have no prior-season stats at all, and the spec's nine-game filter also
removes anyone who missed most of last year. Both groups go early in real
drafts, so leaving them unscored would mean the bot silently refuses to ever
recommend them.

The fix is to learn what the market's ADP implies about VOR from the players who
*do* have data, then read an imputed VOR off that curve. VOR falls off roughly
logarithmically in ADP rank, so a linear fit of ``vor ~ log(adp_rank)`` is a good
approximation and is monotone by construction.
"""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd

log = logging.getLogger(__name__)

MIN_FIT_SAMPLES = 20


def fit_adp_vor_curve(frame: pd.DataFrame) -> tuple[float, float]:
    """Least-squares fit of ``vor = slope * log(adp_rank) + intercept``.

    Returns the ``(slope, intercept)`` pair. Slope is expected to be negative --
    later ADP means less value.
    """
    known = frame[frame["vor"].notna() & frame["adp_rank"].notna()]
    if len(known) < MIN_FIT_SAMPLES:
        raise ValueError(
            f"need at least {MIN_FIT_SAMPLES} players with both VOR and ADP to fit "
            f"the imputation curve, got {len(known)}"
        )

    x = np.log(known["adp_rank"].to_numpy(dtype=float))
    y = known["vor"].to_numpy(dtype=float)
    slope, intercept = np.polyfit(x, y, 1)
    log.info(
        "ADP->VOR curve fit on %d players: vor = %.3f * ln(adp_rank) + %.3f",
        len(known),
        slope,
        intercept,
    )
    return float(slope), float(intercept)


def impute_missing_vor(frame: pd.DataFrame) -> pd.DataFrame:
    """Fill null VOR from ADP, flagging each imputed row.

    Imputed values are clipped at the worst observed real VOR so an unknown
    player can never be ranked above the actual data supports.
    """
    result = frame.copy()
    missing = result["vor"].isna() & result["adp_rank"].notna()
    if not missing.any():
        return result

    slope, intercept = fit_adp_vor_curve(result)
    imputed = slope * np.log(result.loc[missing, "adp_rank"].astype(float)) + intercept

    ceiling = float(result["vor"].max())
    floor = float(result["vor"].min())
    result.loc[missing, "vor"] = imputed.clip(lower=floor, upper=ceiling)
    result.loc[missing, "vor_imputed"] = True

    log.info("imputed VOR for %d players without a usable prior season", int(missing.sum()))
    return result
