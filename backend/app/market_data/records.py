"""An asset's price records (docs/market-data.md#price-records): its highest
or lowest price in its stored history, the last year or the last half year,
reached today (UTC) - one message per asset per day (the widest window it
broke), checked by the risk engine every RECORDS_CHECK_SECONDS."""

import logging
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Literal

from sqlalchemy import func, select

from app.db import async_session
from app.market_data.assets import configured_assets
from app.market_data.models import Candle
from app.notifications.alerts import alert
from app.watchdog.redis_client import mark_once

logger = logging.getLogger(__name__)

RECORDS_CHECK_SECONDS = 15 * 60
# Widest first: a record of the whole history is told as that, not as the year's.
WINDOWS: tuple[tuple[str, timedelta | None], ...] = (
    ("its stored history", None),
    ("a year", timedelta(days=365)),
    ("half a year", timedelta(days=182)),
)

Kind = Literal["high", "low"]


@dataclass(frozen=True)
class Before:
    """A window's range before today."""

    name: str
    high: Decimal
    low: Decimal


@dataclass(frozen=True)
class Record:
    kind: Kind
    window: str
    price: Decimal  # today's high or low
    before: Decimal  # the window's before today


def broken(today_high: Decimal, today_low: Decimal, windows: list[Before]) -> Record | None:
    """The record today set - the widest window broken (a new high before a
    new low when both); None without one."""
    for w in windows:
        if today_high > w.high:
            return Record("high", w.name, today_high, w.high)
    for w in windows:
        if today_low < w.low:
            return Record("low", w.name, today_low, w.low)
    return None


def message(asset: str, record: Record, since: date | None) -> str:
    arrow = "📈" if record.kind == "high" else "📉"
    word = "highest" if record.kind == "high" else "lowest"
    window = f"{record.window} (since {since.isoformat()})" if since else record.window
    return (
        f"{arrow} {asset} at its {word} price in {window}: {record.price:,.2f} "
        f"(before: {record.before:,.2f})"
    )


async def _deepest_interval(asset: str) -> tuple[str, datetime] | None:
    """The stored interval reaching back furthest, and its first candle."""
    async with async_session() as session:
        rows = (
            await session.execute(
                select(Candle.interval, func.min(Candle.open_time))
                .where(Candle.asset == asset)
                .group_by(Candle.interval)
            )
        ).all()
    found = [(interval, first) for interval, first in rows if first is not None]
    return min(found, key=lambda r: r[1]) if found else None


async def _range(
    asset: str, interval: str, start: datetime | None, end: datetime | None
) -> tuple[Decimal, Decimal] | None:
    async with async_session() as session:
        query = select(func.max(Candle.high), func.min(Candle.low)).where(
            Candle.asset == asset, Candle.interval == interval
        )
        if start is not None:
            query = query.where(Candle.open_time >= start)
        if end is not None:
            query = query.where(Candle.open_time < end)
        high, low = (await session.execute(query)).one()
    return None if high is None or low is None else (Decimal(high), Decimal(low))


async def check_asset(asset: str, now: datetime) -> None:
    deepest = await _deepest_interval(asset)
    if deepest is None:
        return
    interval, first = deepest
    today = datetime.combine(now.date(), datetime.min.time(), UTC)
    todays = await _range(asset, interval, today, None)
    if todays is None or first >= today:
        return
    windows: list[Before] = []
    for name, span in WINDOWS:
        start = None if span is None else today - span
        if start is not None and first > start:
            continue  # the history doesn't reach back that far
        before = await _range(asset, interval, start, today)
        if before is not None:
            windows.append(Before(name, *before))
    record = broken(*todays, windows)
    if record is None:
        return
    if not await mark_once(f"records:{asset}:{now.date().isoformat()}", 2 * 24 * 3600):
        return  # told already today
    since = first.date() if record.window == WINDOWS[0][0] else None
    await alert("market-data", "info", message(asset, record, since))


async def check_records() -> None:
    now = datetime.now(UTC)
    for asset in await configured_assets():
        try:
            await check_asset(asset, now)
        except Exception:
            logger.exception("%s: price records check failed", asset)
