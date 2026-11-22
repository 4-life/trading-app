"""The crypto Fear & Greed index (0 extreme fear - 100 extreme greed) - the
core's ports (FearGreedSource, FearGreedStore) and its cached reading
(latest_fear_greed). The adapters: app/sentiment/alternative_me.py (the
source), app/sentiment/redis_store.py (the last reading, kept across restarts)."""

import logging
import time
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Protocol

logger = logging.getLogger(__name__)

# The index is published once a day: read at most this often.
REFRESH_SECONDS = 3600
# After a failed read, tried again only after this long.
RETRY_SECONDS = 300


@dataclass(frozen=True)
class FearGreed:
    value: int  # 0 - 100
    label: str  # e.g. "Extreme Fear"
    measured_at: datetime
    stale: bool = False  # the last one read: the source can't be read now


class FearGreedSource(Protocol):
    async def latest(self) -> FearGreed: ...


class FearGreedStore(Protocol):
    async def save(self, reading: FearGreed) -> None: ...

    async def load(self) -> FearGreed | None: ...


_cached: tuple[float, FearGreed | None] | None = None


async def latest_fear_greed(source: FearGreedSource, store: FearGreedStore) -> FearGreed | None:
    """The latest reading, cached; while the source can't be read, the last
    one read (marked stale) - from the store after a restart; None if none
    was ever read."""
    global _cached
    now = time.monotonic()
    if _cached is not None:
        read_at, reading = _cached
        if now - read_at < (RETRY_SECONDS if reading is None or reading.stale else REFRESH_SECONDS):
            return reading
    try:
        reading = await source.latest()
    except Exception:
        logger.warning("fear & greed index could not be read", exc_info=True)
        last = _cached[1] if _cached is not None else None
        if last is None:
            try:
                last = await store.load()
            except Exception:
                logger.warning("the last fear & greed reading could not be loaded", exc_info=True)
        stale = None if last is None else replace(last, stale=True)
        _cached = (now, stale)
        return stale
    _cached = (now, reading)
    try:
        await store.save(reading)
    except Exception:
        logger.warning("the fear & greed reading could not be saved", exc_info=True)
    return reading
