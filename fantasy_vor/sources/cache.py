"""Parquet cache so a live draft never waits on a scrape.

Every source function goes through :func:`cached` -- it returns the cached frame
when one exists, otherwise calls the loader and writes the result.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Callable

import pandas as pd

log = logging.getLogger(__name__)

DATA_DIR = Path(__file__).resolve().parents[2] / "data"


def cache_path(key: str) -> Path:
    return DATA_DIR / f"{key}.parquet"


def cached(key: str, loader: Callable[[], pd.DataFrame], refresh: bool = False) -> pd.DataFrame:
    """Return ``loader()``'s frame, reading from / writing to the parquet cache."""
    path = cache_path(key)
    if path.exists() and not refresh:
        log.debug("cache hit: %s", path.name)
        return pd.read_parquet(path)

    log.info("fetching %s", key)
    frame = loader()
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(path, index=False)
    log.info("cached %s (%d rows)", key, len(frame))
    return frame


def clear(key: str | None = None) -> None:
    """Drop one cache entry, or the whole cache when ``key`` is None."""
    if key is not None:
        cache_path(key).unlink(missing_ok=True)
        return
    if DATA_DIR.exists():
        for path in DATA_DIR.glob("*.parquet"):
            path.unlink()
