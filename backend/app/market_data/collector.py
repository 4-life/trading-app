import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, cast

from hyperliquid.utils.error import ClientError
from sqlalchemy import CursorResult, delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.config import settings
from app.db import async_session
from app.exchange.base import MarketAdapter
from app.market_data.models import (
    Candle,
    FundingRate,
    OpenInterestSnapshot,
    OrderBookSnapshot,
    Trade,
)
from app.papers.queries import paper_asset_timeframes
from app.scheduling import sleep_until_next
from app.system.exchange_api import data_source
from app.system.models import Setting

logger = logging.getLogger(__name__)

_PRUNE_SECONDS = 3600
# The candle interval the current price is read from (api/portfolio.py, risk engine).
PRICE_INTERVAL = "1m"


def _ms_to_utc(ms: int) -> datetime:
    return datetime.fromtimestamp(ms / 1000, tz=UTC)


def _fmt(ts: datetime) -> str:
    """Log-only formatting - everything here is UTC and minute-granular
    (1-minute candles), so seconds and the +00:00 offset are always the
    same shape and never carry information."""
    return ts.strftime("%Y-%m-%d %H:%M")


def _batched(rows: list[dict[str, Any]], size: int) -> list[list[dict[str, Any]]]:
    return [rows[i : i + size] for i in range(0, len(rows), size)]


def _interval_to_ms(interval: str) -> int:
    multipliers = {"m": 60_000, "h": 3_600_000, "d": 86_400_000}
    return int(interval[:-1]) * multipliers[interval[-1]]


async def _missing_candle_ranges(
    asset: str, interval: str, start_time_ms: int, end_time_ms: int
) -> list[tuple[int, int]]:
    """Only the sub-ranges of [start, end] not already covered by existing
    candles, so rerunning backfill (every `docker compose up`, or a
    targeted historical-test run) only re-requests what's actually
    missing. Detects a hole in the middle too, not just at the head/tail -
    any run of existing candles more than one interval apart - so it
    recovers cleanly from a gap left by downtime, not only a cold start."""
    step_ms = _interval_to_ms(interval)
    async with async_session() as session:
        existing = (
            await session.scalars(
                select(Candle.open_time)
                .where(
                    Candle.asset == asset,
                    Candle.interval == interval,
                    Candle.open_time >= _ms_to_utc(start_time_ms),
                    Candle.open_time <= _ms_to_utc(end_time_ms),
                )
                .order_by(Candle.open_time)
            )
        ).all()

    if not existing:
        return [(start_time_ms, end_time_ms)]

    gaps: list[tuple[int, int]] = []
    cursor = start_time_ms
    for ts in existing:
        ts_ms = int(ts.timestamp() * 1000)
        if ts_ms - cursor > step_ms:
            gaps.append((cursor, ts_ms))
        cursor = max(cursor, ts_ms + step_ms)
    if end_time_ms - cursor > step_ms:
        gaps.append((cursor, end_time_ms))
    return gaps


# end_time_ms is always "right now" at the instant this is called, but
# funding rows only land every few minutes, not continuously - requiring
# latest >= end_time_ms exactly meant "covered" was essentially never true
# for the one-shot backfill (confirmed live 2026-09-24: forced a full
# re-fetch, and its REST call, on every single `docker compose up`
# regardless of how complete the data already was). This tolerance is
# generous relative to funding's real update cadence, and is only passed
# by market_data/backfill.py's one-shot backfill below - NOT by
# MarketDataCollector._poll_funding's default (see backfill_funding's own
# comment): that poll loop's whole job is to notice new rows landing every
# funding_poll_seconds, and an hour of slack there would make it think
# it's "covered" long after new data actually arrived, silently stalling
# live funding collection instead of just avoiding a redundant startup call.
FUNDING_COVERAGE_TOLERANCE = timedelta(hours=1)
# The provider's funding of a range begins up to this late - its first
# interval(s) after the range's start (Lighter: ~17h of a year's range), or
# after the asset's listing.
FUNDING_LISTING_SLACK = timedelta(days=1)


def _funding_history_start_key(provider: str, asset: str) -> str:
    return f"funding_history_start:{provider}:{asset}"


async def _funding_bounds(asset: str) -> tuple[datetime | None, datetime | None]:
    """The asset's earliest and latest stored funding rows."""
    async with async_session() as session:
        earliest = await session.scalar(
            select(FundingRate.exchange_timestamp)
            .where(FundingRate.asset == asset)
            .order_by(FundingRate.exchange_timestamp)
            .limit(1)
        )
        latest = await session.scalar(
            select(FundingRate.exchange_timestamp)
            .where(FundingRate.asset == asset)
            .order_by(FundingRate.exchange_timestamp.desc())
            .limit(1)
        )
    return earliest, latest


def funding_covered(
    earliest: datetime | None,
    latest: datetime | None,
    start: datetime,
    end: datetime,
    tolerance: timedelta,
    history_start: datetime | None,
) -> bool:
    """Coarser than candles' gap detection - just checks the requested range
    falls within the stored rows (`earliest` -> `latest`), not that every
    interval inside it is present: from the range's start - or the
    provider's funding history start, once a backfill found it later
    (`history_start`) - give or take FUNDING_LISTING_SLACK, to `end` within
    `tolerance`. Skips the common case: rerunning backfill when nothing's
    changed."""
    if earliest is None or latest is None:
        return False
    begins = start if history_start is None else max(start, history_start)
    return earliest <= begins + FUNDING_LISTING_SLACK and latest >= end - tolerance


# Hyperliquid's candleSnapshot endpoint silently truncates to roughly 5000
# rows per request rather than paginating - a multi-day backfill has to chunk
# its requests or it quietly loses the tail of the range. Sized per interval
# (candle count, not a fixed calendar window) - a fixed 3-day window (this
# constant's original, "1m"-only design) requests only ~18 "4h" candles per
# call, forcing 240+ tiny requests for a single 730-day backfill instead of
# ~2. Confirmed live 2026-09-25: that alone triggered Hyperliquid's rate
# limit (HTTP 429, request 65/202) the first time market-data backfilled all
# five standard scales instead of just two (see
# docs/market-data.md#historical-backfill) - the fix is not sending 100x
# more requests than the data needs.
CANDLES_PER_CHUNK = 4000


def _chunk_ms_for_interval(interval: str) -> int:
    return CANDLES_PER_CHUNK * _interval_to_ms(interval)


# Retry with backoff - a burst of 429s
# under concurrent multi-asset/multi-interval backfill contention shouldn't
# abandon that chunk (and everything after it for this asset) on the first
# hit, once the chunk-sizing fix above still isn't enough on its own (e.g.
# several assets' backfills genuinely running at once).
_RATE_LIMIT_MAX_RETRIES = 3
_RATE_LIMIT_RETRY_DELAY_SECONDS = 5.0


async def get_candles_with_retry(
    adapter: MarketAdapter, asset: str, interval: str, start_time_ms: int, end_time_ms: int
) -> list[dict[str, Any]]:
    for attempt in range(_RATE_LIMIT_MAX_RETRIES + 1):
        try:
            return await adapter.get_candles(asset, interval, start_time_ms, end_time_ms)
        except ClientError as e:
            if e.status_code != 429 or attempt == _RATE_LIMIT_MAX_RETRIES:
                raise
            logger.warning(
                "%s: rate limited (429) fetching %s candles, retrying in %.0fs (attempt %d/%d)",
                asset,
                interval,
                _RATE_LIMIT_RETRY_DELAY_SECONDS,
                attempt + 1,
                _RATE_LIMIT_MAX_RETRIES,
            )
            await asyncio.sleep(_RATE_LIMIT_RETRY_DELAY_SECONDS)
    raise AssertionError("unreachable - loop above always returns or raises")


# Postgres/asyncpg hard-caps bind parameters at 32,767 per query - a
# CANDLES_PER_CHUNK-sized chunk's row count x 8 columns can exceed that on
# its own for a fine interval (confirmed: 3646 candles x 8 = 29,168). Every
# multi-row insert here batches at this size rather than trusting the
# caller's chunk size to also happen to be safe for Postgres (see
# app/feature_engine/backfill.py, which hit exactly this and silently wrote
# nothing on every run until it was fixed the same way) - independent of
# CANDLES_PER_CHUNK above, which only bounds how much is requested from
# Hyperliquid per call, not how much is inserted per query.
INSERT_BATCH_SIZE = 2000


def _history_start_key(provider: str, asset: str, interval: str) -> str:
    return f"candle_history_start:{provider}:{asset}:{interval}"


async def _history_start(key: str) -> int | None:
    """Where the provider's history of an asset's interval (or its funding)
    begins (ms) - nothing before it - once a backfill found out; None until then."""
    async with async_session() as session:
        row = await session.get(Setting, key)
    return None if row is None else int(row.value)


async def _save_history_start(key: str, start_ms: int) -> None:
    now = datetime.now(UTC)
    stmt = pg_insert(Setting).values(key=key, value=str(start_ms), encrypted=False, updated_at=now)
    stmt = stmt.on_conflict_do_update(
        index_elements=["key"], set_={"value": str(start_ms), "updated_at": now}
    )
    async with async_session() as session:
        await session.execute(stmt)
        await session.commit()


async def backfill_candles(
    adapter: MarketAdapter, asset: str, interval: str, start_time_ms: int, end_time_ms: int
) -> int:
    """The missing candles of [start, end]. The range before the provider's
    history of the asset begins (its listing) has none: once a request for
    the range before the first stored candle finds that out, it's saved in
    `settings` (per provider, asset and interval) and never requested again
    - not on later runs, nor with a longer BACKFILL_DAYS."""
    key = _history_start_key((await data_source()).provider, asset, interval)
    history_start = await _history_start(key)
    missing = await _missing_candle_ranges(asset, interval, start_time_ms, end_time_ms)
    if history_start is not None:
        missing = [(max(s, history_start), e) for s, e in missing if e > history_start]
    if not missing:
        logger.info(
            "%s: candles already cover %s -> %s, nothing to fetch",
            asset,
            _fmt(_ms_to_utc(start_time_ms)),
            _fmt(_ms_to_utc(end_time_ms)),
        )
        return 0

    count = 0
    step_ms = _interval_to_ms(interval)
    for range_start, range_end in missing:
        fetched, first_ms = await _fetch_candle_range(
            adapter, asset, interval, range_start, range_end
        )
        count += fetched
        if range_start != start_time_ms:
            continue
        # The range before the first stored candle: the provider's history
        # begins at its first candle here - else, nothing came back, at the
        # stored candle after the range.
        begins = first_ms
        if begins is None and range_end < end_time_ms:
            begins = range_end
        if begins is not None and begins - range_start > step_ms:
            await _save_history_start(key, begins)
            logger.info(
                "%s: %s history begins %s - not requested before it again",
                asset,
                interval,
                _fmt(_ms_to_utc(begins)),
            )
    return count


async def _fetch_candle_range(
    adapter: MarketAdapter, asset: str, interval: str, start_time_ms: int, end_time_ms: int
) -> tuple[int, int | None]:
    """The candles stored and the first one's open time (ms), None without any."""
    count = 0
    first_ms: int | None = None
    chunk_start = start_time_ms
    chunk_num = 0
    chunk_ms = _chunk_ms_for_interval(interval)
    total_chunks = -(-(end_time_ms - start_time_ms) // chunk_ms)  # ceil division
    while chunk_start < end_time_ms:
        chunk_num += 1
        chunk_end = min(chunk_start + chunk_ms, end_time_ms)
        logger.info(
            "%s: requesting %s candles chunk %d/%d (%s -> %s)",
            asset,
            interval,
            chunk_num,
            total_chunks,
            _fmt(_ms_to_utc(chunk_start)),
            _fmt(_ms_to_utc(chunk_end)),
        )
        t0 = time.monotonic()
        candles = await get_candles_with_retry(adapter, asset, interval, chunk_start, chunk_end)
        logger.info(
            "%s: chunk %d/%d returned %d candles in %.1fs",
            asset,
            chunk_num,
            total_chunks,
            len(candles),
            time.monotonic() - t0,
        )
        if candles:
            if first_ms is None:
                first_ms = min(int(c["t"]) for c in candles)
            # Batched multi-row upserts (well under Postgres' bind-param
            # limit) instead of one round-trip per row - the latter is what
            # made a multi-day backfill so slow.
            rows = [
                {
                    "asset": asset,
                    "interval": interval,
                    "open": Decimal(c["o"]),
                    "high": Decimal(c["h"]),
                    "low": Decimal(c["l"]),
                    "close": Decimal(c["c"]),
                    "volume": Decimal(c["v"]),
                    "open_time": _ms_to_utc(c["t"]),
                }
                for c in candles
            ]
            async with async_session() as session:
                for batch in _batched(rows, INSERT_BATCH_SIZE):
                    stmt = pg_insert(Candle).values(batch)
                    stmt = stmt.on_conflict_do_update(
                        index_elements=["asset", "interval", "open_time"],
                        set_={
                            "open": stmt.excluded.open,
                            "high": stmt.excluded.high,
                            "low": stmt.excluded.low,
                            "close": stmt.excluded.close,
                            "volume": stmt.excluded.volume,
                        },
                    )
                    await session.execute(stmt)
                await session.commit()
            count += len(candles)
        chunk_start = chunk_end
    return count, first_ms


async def backfill_funding(
    adapter: MarketAdapter,
    asset: str,
    start_time_ms: int,
    end_time_ms: int,
    coverage_tolerance: timedelta = timedelta(0),
) -> int:
    """coverage_tolerance defaults to exact (0) - right for
    MarketDataCollector._poll_funding's every-cycle freshness check.
    market_data/backfill.py's one-shot backfill passes
    FUNDING_COVERAGE_TOLERANCE explicitly instead (see its comment above -
    a one-shot startup call has very different staleness tolerance than a
    live poll loop does)."""
    key = _funding_history_start_key((await data_source()).provider, asset)
    saved = await _history_start(key)
    history_start = None if saved is None else _ms_to_utc(saved)
    earliest, latest = await _funding_bounds(asset)
    start, end = _ms_to_utc(start_time_ms), _ms_to_utc(end_time_ms)
    if funding_covered(earliest, latest, start, end, coverage_tolerance, history_start):
        logger.info(
            "%s: funding history already covers %s -> %s, nothing to fetch",
            asset,
            _fmt(_ms_to_utc(start_time_ms)),
            _fmt(_ms_to_utc(end_time_ms)),
        )
        return 0

    logger.info("%s: requesting funding history", asset)
    t0 = time.monotonic()
    history = await adapter.get_funding_history(asset, start_time_ms, end_time_ms)
    logger.info(
        "%s: funding history returned %d rows in %.1fs", asset, len(history), time.monotonic() - t0
    )
    if not history:
        return 0
    first_ms = min(int(f["time"]) for f in history)
    if (earliest is None or start < earliest) and first_ms > start_time_ms:
        # A request reaching before the stored rows: the provider's funding
        # history begins at its first row - remembered, so a later run doesn't
        # fetch the whole range again to find nothing before it.
        await _save_history_start(key, first_ms)
    rows = [
        {
            "asset": asset,
            "funding_rate": Decimal(f["fundingRate"]),
            "premium": Decimal(f["premium"]),
            "exchange_timestamp": _ms_to_utc(f["time"]),
        }
        for f in history
    ]
    async with async_session() as session:
        for batch in _batched(rows, INSERT_BATCH_SIZE):
            stmt = pg_insert(FundingRate).values(batch)
            stmt = stmt.on_conflict_do_update(
                index_elements=["asset", "exchange_timestamp"],
                set_={
                    "funding_rate": stmt.excluded.funding_rate,
                    "premium": stmt.excluded.premium,
                },
            )
            await session.execute(stmt)
        await session.commit()
    return len(history)


class MarketDataCollector:
    def __init__(self, adapter: MarketAdapter, assets: list[str]) -> None:
        self._adapter = adapter
        # Coins the provider doesn't list (e.g. Lighter's XAU on Hyperliquid)
        # are skipped once, with a warning - not an error on every poll.
        self._assets = [a for a in assets if adapter.is_listed(a)]
        unlisted = [a for a in assets if not adapter.is_listed(a)]
        if unlisted:
            logger.warning("not listed by the provider - not collected: %s", ", ".join(unlisted))
        # One cursor per standard scale, not just two - each interval polls
        # forward from wherever it last left off independently, same reason
        # candle/scalp-candle needed separate cursors before.
        self._candle_poll_end_ms: dict[str, int] = {}
        self._funding_poll_end_ms: int | None = None
        # Set on every trade/book message, and reset to "now" whenever
        # subscriptions are (re)established - _check_ws_health compares
        # against this, not just a per-message counter, so a WS that never
        # delivers a single message after connecting is caught too, not
        # only one that goes silent after working for a while.
        self._last_ws_message_at: datetime = datetime.now(UTC)

    async def start(self) -> None:
        await self._subscribe_all()
        await asyncio.gather(
            # Aligned to the clock: candles close on minute boundaries, so a
            # closed candle is stored ~2 s after its close (app/scheduling.py).
            self._poll_loop(self._poll_candles, settings.candle_poll_seconds, offset_seconds=2),
            self._poll_loop(self._poll_funding, settings.funding_poll_seconds),
            self._poll_loop(self._poll_open_interest, settings.open_interest_poll_seconds),
            self._poll_loop(self._check_ws_health, settings.ws_health_check_seconds),
            self._poll_loop(self._prune_raw_data, _PRUNE_SECONDS),
        )

    async def _subscribe_all(self) -> None:
        for asset in self._assets:
            try:
                self._adapter.subscribe_trades(asset, self._on_trade)
                self._adapter.subscribe_l2_book(asset, self._on_book)
            except Exception:
                # An asset Hyperliquid doesn't recognize (wrong name, or not
                # a perpetual - see docs/market-data.md) shouldn't take down
                # collection for every other, valid asset.
                logger.exception("failed to subscribe to %s - skipping it", asset)
        self._last_ws_message_at = datetime.now(UTC)

    async def _check_ws_health(self) -> None:
        # The SDK's WebsocketManager doesn't auto-reconnect once the
        # underlying socket drops (see MarketAdapter.reconnect_ws) -
        # trade/book messages just silently stop forever otherwise, with
        # candle/funding REST polling continuing normally and masking it
        # until watchdog's own, much coarser staleness check eventually
        # notices. This self-heals before that, on its own.
        age = (datetime.now(UTC) - self._last_ws_message_at).total_seconds()
        if age <= settings.ws_stale_seconds:
            return
        logger.warning(
            "no WS message in %.0fs (threshold %.0fs) - reconnecting",
            age,
            settings.ws_stale_seconds,
        )
        await self._adapter.reconnect_ws()
        await self._subscribe_all()
        logger.info("WS reconnected and re-subscribed to %d asset(s)", len(self._assets))

    async def _poll_loop(
        self,
        fn: Callable[[], Awaitable[None]],
        interval_seconds: int,
        offset_seconds: float | None = None,
    ) -> None:
        """`offset_seconds` set: run at clock multiples of the interval plus
        the offset, instead of every interval from whenever it started."""
        while True:
            try:
                await fn()
            except Exception:
                logger.exception("market-data poll loop %s failed", fn.__name__)
            if offset_seconds is None:
                await asyncio.sleep(interval_seconds)
            else:
                await sleep_until_next(interval_seconds, offset_seconds)

    async def _on_trade(self, msg: dict[str, Any]) -> None:
        if msg.get("channel") != "trades":
            return
        now = datetime.now(UTC)
        self._last_ws_message_at = now
        async with async_session() as session:
            for t in msg["data"]:
                session.add(
                    Trade(
                        asset=t["coin"],
                        price=Decimal(t["px"]),
                        size=Decimal(t["sz"]),
                        side=t["side"],
                        exchange_timestamp=_ms_to_utc(t["time"]),
                        collected_at=now,
                    )
                )
            await session.commit()

    async def _on_book(self, msg: dict[str, Any]) -> None:
        if msg.get("channel") != "l2Book":
            return
        data = msg["data"]
        bids, asks = data["levels"]
        if not bids or not asks:
            return
        now = datetime.now(UTC)
        self._last_ws_message_at = now
        async with async_session() as session:
            session.add(
                OrderBookSnapshot(
                    asset=data["coin"],
                    best_bid=Decimal(bids[0]["px"]),
                    best_ask=Decimal(asks[0]["px"]),
                    bid_depth=sum(Decimal(lvl["sz"]) for lvl in bids),
                    ask_depth=sum(Decimal(lvl["sz"]) for lvl in asks),
                    exchange_timestamp=_ms_to_utc(data["time"]),
                    collected_at=now,
                )
            )
            await session.commit()

    async def _paper_pairs(self) -> list[tuple[str, str]]:
        """Enabled papers' (asset, timeframe) outside ASSETS - coins a scanner
        picked (docs/market-data.md#collected-data). Candles at the paper's
        timeframe and 1m (the price); no WebSocket."""
        pairs = await paper_asset_timeframes(enabled_only=True)
        return [(a, tf) for a, tf in pairs if a not in self._assets and self._adapter.is_listed(a)]

    async def _poll_candles(self) -> None:
        end = int(datetime.now(UTC).timestamp() * 1000)
        starts: dict[str, int] = {}
        for interval in settings.candle_intervals:
            # Always re-fetch (and upsert) the last closed candle and the
            # forming one: a candle row is first written while it's still
            # forming, and only a fetch after its close stores its final
            # values - signals run on closed candles only.
            refresh_start = end - 2 * _interval_to_ms(interval)
            starts[interval] = min(
                self._candle_poll_end_ms.get(interval, refresh_start), refresh_start
            )
        # Every (asset, interval) concurrently - one after another they took
        # several seconds, delaying the closed candle (and every signal).
        pairs = [(a, i) for i in settings.candle_intervals for a in self._assets]
        extra = await self._paper_pairs()
        # Their paper's timeframe, plus 1m: the current price everything reads
        # (portfolio, risk engine) comes from the latest 1m candle.
        extra_pairs = {(a, tf) for a, tf in extra} | {(a, PRICE_INTERVAL) for a, _ in extra}
        pairs += sorted(p for p in extra_pairs if p[1] in starts)
        await asyncio.gather(
            *(
                self._poll_asset_candles(asset, interval, starts[interval], end)
                for asset, interval in pairs
            )
        )
        for interval in settings.candle_intervals:
            self._candle_poll_end_ms[interval] = end

    async def _poll_asset_candles(self, asset: str, interval: str, start: int, end: int) -> None:
        try:
            await _fetch_candle_range(self._adapter, asset, interval, start, end)
        except Exception:
            logger.exception("candle poll failed for %s at %s", asset, interval)

    async def _prune_raw_data(self) -> None:
        """Deletes trades and order-book snapshots older than
        RAW_DATA_RETENTION_HOURS - see docs/market-data.md#data-retention."""
        cutoff = datetime.now(UTC) - timedelta(hours=settings.raw_data_retention_hours)
        async with async_session() as session, session.begin():
            trades = cast(
                CursorResult[Any],
                await session.execute(delete(Trade).where(Trade.exchange_timestamp < cutoff)),
            )
            books = cast(
                CursorResult[Any],
                await session.execute(
                    delete(OrderBookSnapshot).where(OrderBookSnapshot.exchange_timestamp < cutoff)
                ),
            )
        logger.info(
            "retention: deleted %d trades, %d order-book snapshots older than %s",
            trades.rowcount,
            books.rowcount,
            cutoff.isoformat(timespec="seconds"),
        )

    async def _poll_funding(self) -> None:
        end = int(datetime.now(UTC).timestamp() * 1000)
        start = self._funding_poll_end_ms or (end - settings.funding_poll_seconds * 1000)
        extra = sorted({a for a, _ in await self._paper_pairs()})
        for asset in [*self._assets, *extra]:
            try:
                await backfill_funding(self._adapter, asset, start, end)
            except Exception:
                logger.exception("funding poll failed for %s", asset)
        self._funding_poll_end_ms = end

    async def _get_asset_contexts_with_retry(
        self,
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        # Same retry as get_candles_with_retry above (same constants - no
        # evidence OI polling needs different tuning) - this call had none
        # at all before, so a single 429 skipped that whole poll cycle's OI
        # snapshot with a full traceback logged, rather than a quiet retry
        # like every other Hyperliquid REST call here already gets
        # (confirmed live 2026-09-25).
        for attempt in range(_RATE_LIMIT_MAX_RETRIES + 1):
            try:
                return await self._adapter.get_asset_contexts()
            except ClientError as e:
                if e.status_code != 429 or attempt == _RATE_LIMIT_MAX_RETRIES:
                    raise
                logger.warning(
                    "rate limited (429) fetching asset contexts, retrying in %.0fs (attempt %d/%d)",
                    _RATE_LIMIT_RETRY_DELAY_SECONDS,
                    attempt + 1,
                    _RATE_LIMIT_MAX_RETRIES,
                )
                await asyncio.sleep(_RATE_LIMIT_RETRY_DELAY_SECONDS)
        raise AssertionError("unreachable - loop above always returns or raises")

    async def _poll_open_interest(self) -> None:
        universe, asset_ctxs = await self._get_asset_contexts_with_retry()
        now = datetime.now(UTC)
        async with async_session() as session:
            for meta, ctx in zip(universe["universe"], asset_ctxs, strict=True):
                if meta["name"] not in self._assets:
                    continue
                session.add(
                    OpenInterestSnapshot(
                        asset=meta["name"],
                        open_interest=Decimal(ctx["openInterest"]),
                        collected_at=now,
                    )
                )
            await session.commit()
