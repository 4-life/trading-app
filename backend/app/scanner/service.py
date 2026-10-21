"""Scanner service (docs/papers.md#scanner-papers): for every scanner paper,
after each candle close at its timeframe - rank the market's perpetuals by
24h volume, find the top ones breaking out now (the executor's own entry
rule), backfill them and create / re-enable a single paper for each, and
disable the flat ones whose coin isn't breaking out any more. The single
papers then trade like any other paper."""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.config import settings
from app.db import async_session
from app.exchange.base import MarketAdapter
from app.execution_engine.models import IN_FLIGHT_OUTCOMES, Position, TradingDecision
from app.executors.base import direction_allowed, recent_candles
from app.executors.trend import (
    BEAR_SMA_DAYS,
    BREAKOUT_DAYS,
    REGIME_ASSET,
    Bar,
    bars_for_days,
    bear_market,
    decide_signal,
)
from app.feature_engine.engine import INTERVAL_MINUTES
from app.market_data.collector import (
    FUNDING_COVERAGE_TOLERANCE,
    backfill_candles,
    backfill_funding,
    get_candles_with_retry,
)
from app.notifications.alerts import alert
from app.papers.models import Paper
from app.risk_engine.blocks import unblock_paper
from app.scanner.rules import Child, plan, top_by_volume
from app.system.exchange_api import get_exchange_api

logger = logging.getLogger(__name__)

SERVICE = "scanner"
# A candle is scanned this long after its close - Hyperliquid's REST has it final by then.
SETTLE_SECONDS = 10
CONCURRENT_FETCHES = 4

CandidateRule = Callable[[MarketAdapter, Paper, list[str], int], Awaitable[list[str]]]


async def trend_candidates(
    adapter: MarketAdapter, scanner: Paper, universe: list[str], closed_ms: int
) -> list[str]:
    """Coins whose last closed candle is a trend breakout in a direction the
    scanner allows - exactly the trend executor's entry rule."""
    step_ms = INTERVAL_MINUTES[scanner.timeframe] * 60_000
    breakout = bars_for_days(BREAKOUT_DAYS, scanner.timeframe)
    window = bars_for_days(BEAR_SMA_DAYS, scanner.timeframe)
    btc = await recent_candles(REGIME_ASSET, scanner.timeframe, window)
    bear = bear_market([float(c.close) for c in btc], window)
    start = closed_ms - (breakout + 40) * step_ms
    gate = asyncio.Semaphore(CONCURRENT_FETCHES)

    async def breaking_out(coin: str) -> bool:
        async with gate:
            try:
                raw = await get_candles_with_retry(
                    adapter, coin, scanner.timeframe, start, closed_ms - 1
                )
            except Exception:
                logger.exception("scanner: %s candles failed - skipping it", coin)
                return False
        bars = [
            Bar(
                datetime.fromtimestamp(int(c["t"]) / 1000, UTC),
                float(c["h"]),
                float(c["l"]),
                float(c["c"]),
                float(c["v"]),
            )
            for c in raw
            if int(c["t"]) < closed_ms
        ]
        signal = decide_signal(bars, breakout, None, bear)
        return signal is not None and direction_allowed(scanner.direction, signal.direction)

    hits = await asyncio.gather(*(breaking_out(c) for c in universe))
    return [coin for coin, hit in zip(universe, hits, strict=True) if hit]


# Executors a scanner paper can run, with their "breaking out now" rule.
CANDIDATE_RULES: dict[str, CandidateRule] = {"trend": trend_candidates}


async def _children(scanner: Paper) -> list[Child]:
    async with async_session() as session:
        papers = (await session.scalars(select(Paper).where(Paper.parent_id == scanner.id))).all()
        out = []
        for p in papers:
            busy = await session.scalar(
                select(Position.id).where(Position.paper_id == p.id, Position.closed_at.is_(None))
            ) or await session.scalar(
                select(TradingDecision.id).where(
                    TradingDecision.paper_id == p.id,
                    TradingDecision.outcome.in_(IN_FLIGHT_OUTCOMES),
                )
            )
            out.append(Child(p.id, p.asset, p.enabled, p.disabled_by, busy is not None))
    return out


async def _child_mode(scanner: Paper) -> str:
    """Live as soon as an exchange API is set (and the leverage is a whole
    number, the exchanges' rule) - no "Go live" click; demo otherwise. Live
    papers still trade only while live auto-trading is on."""
    whole = scanner.leverage == int(scanner.leverage)
    return "live" if whole and await get_exchange_api() is not None else "demo"


async def _taken_assets(scanner: Paper, mode: str) -> set[str]:
    """Coins with an enabled live paper outside this scanner - one live paper per asset."""
    if mode != "live":
        return set()
    async with async_session() as session:
        rows = await session.scalars(
            select(Paper.asset).where(
                Paper.mode == "live",
                Paper.enabled.is_(True),
                Paper.kind == "single",
                Paper.parent_id.is_distinct_from(scanner.id),
            )
        )
        return set(rows.all())


async def _backfill(adapter: MarketAdapter, asset: str, timeframe: str) -> None:
    end = datetime.now(UTC)
    start_ms = int((end - timedelta(days=settings.backfill_days)).timestamp() * 1000)
    end_ms = int(end.timestamp() * 1000)
    await backfill_candles(adapter, asset, timeframe, start_ms, end_ms)
    await backfill_funding(
        adapter, asset, start_ms, end_ms, coverage_tolerance=FUNDING_COVERAGE_TOLERANCE
    )


async def apply(adapter: MarketAdapter, scanner: Paper, candidates: list[str] | None) -> None:
    """`candidates` None: the scanner is disabled - only disable flat children."""
    children = await _children(scanner)
    mode = await _child_mode(scanner)
    todo = plan(
        children,
        candidates or [],
        settings.scanner_max_active,
        await _taken_assets(scanner, mode),
        scanning=candidates is not None,
    )
    now = datetime.now(UTC)
    for paper_id in todo.disable:
        async with async_session() as session, session.begin():
            p = await session.get(Paper, paper_id)
            if p is not None and p.enabled:
                p.enabled, p.disabled_by = False, "scanner"
                p.disabled_reason = "scanner: no longer breaking out"
                p.updated_at = now
                logger.info("scanner %d: disabled paper %d (%s)", scanner.id, p.id, p.asset)
    by_id = {c.paper_id: c for c in children}
    for paper_id in todo.enable:
        await _backfill(adapter, by_id[paper_id].asset, scanner.timeframe)
        async with async_session() as session, session.begin():
            p = await session.get(Paper, paper_id)
            if p is None:
                continue
            # Flat while disabled, so its mode can follow the exchange API.
            p.enabled, p.enabled_at, p.mode = True, now, mode
            p.disabled_by = p.disabled_reason = None
            p.updated_at = now
        await unblock_paper(paper_id)
        message = f"scanner #{scanner.id}: {p.asset} is breaking out - paper #{p.id} on"
        await alert(SERVICE, "info", message)
    for asset in todo.create:
        await _backfill(adapter, asset, scanner.timeframe)
        async with async_session() as session, session.begin():
            p = Paper(
                kind="single",
                parent_id=scanner.id,
                asset=asset,
                timeframe=scanner.timeframe,
                leverage=scanner.leverage,
                direction=scanner.direction,
                executor=scanner.executor,
                mode=mode,
                enabled=True,
                enabled_at=now,
                created_at=now,
                updated_at=now,
            )
            session.add(p)
        message = f"scanner #{scanner.id}: {asset} is breaking out - created paper #{p.id}"
        await alert(SERVICE, "info", message)


class Scanner:
    def __init__(self, adapter: MarketAdapter) -> None:
        self._adapter = adapter
        # scanner paper id -> the candle close it was last scanned at (ms)
        self._scanned: dict[int, int] = {}

    async def run_once(self) -> None:
        async with async_session() as session:
            scanners = (await session.scalars(select(Paper).where(Paper.kind == "scanner"))).all()
        now_ms = int(datetime.now(UTC).timestamp() * 1000)
        universe: list[str] | None = None
        for scanner in scanners:
            try:
                if not scanner.enabled:
                    await apply(self._adapter, scanner, None)
                    continue
                step_ms = INTERVAL_MINUTES[scanner.timeframe] * 60_000
                closed_ms = now_ms // step_ms * step_ms
                if now_ms - closed_ms < SETTLE_SECONDS * 1000:
                    continue
                if self._scanned.get(scanner.id) == closed_ms:
                    continue
                if universe is None:
                    meta, contexts = await self._adapter.get_asset_contexts()
                    universe = top_by_volume(meta, contexts, settings.scanner_top_n)
                rule = CANDIDATE_RULES[scanner.executor]
                candidates = await rule(self._adapter, scanner, universe, closed_ms)
                logger.info(
                    "scanner %d (%s %s): %d of top %d breaking out: %s",
                    scanner.id,
                    scanner.executor,
                    scanner.timeframe,
                    len(candidates),
                    len(universe),
                    ", ".join(candidates) or "-",
                )
                await apply(self._adapter, scanner, candidates)
                self._scanned[scanner.id] = closed_ms
            except Exception:
                logger.exception("scanner %d failed", scanner.id)
