import asyncio
import time


async def sleep_until_next(period_seconds: float, offset_seconds: float = 0.0) -> None:
    """Sleeps until the next wall-clock multiple of `period_seconds`, plus
    `offset_seconds` (e.g. period 60, offset 5 -> hh:mm:05). Candles close on
    minute boundaries, so loops aligned this way react to a close within
    seconds instead of up to a full period later. Staggered offsets keep the
    pipeline in order: candles, then features, then executors."""
    now = time.time()
    next_run = (now - offset_seconds) // period_seconds * period_seconds + period_seconds
    await asyncio.sleep(next_run + offset_seconds - now)
