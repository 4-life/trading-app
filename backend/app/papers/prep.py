"""Paper preparation (docs/papers.md#preparation): a new paper's history is
backfilled - candles at its timeframe, funding, features (and BTC at the same
timeframe for `trend`, its bear filter) - then, if its executor has a
backtest, that's run. papers.prep_status walks backfilling -> backtesting ->
NULL (ready); an error leaves `failed` with the message. Executors don't
trade a paper until it's ready, and it can't be deleted meanwhile.

Runs as a loop in the market-data service (it holds the exchange connection
and owns the data); the status lives in the database, so a restart resumes."""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.backtest.averaging import backtest_paper as backtest_averaging
from app.backtest.regime import backtest_paper as backtest_regime
from app.backtest.supertrend import backtest_paper as backtest_supertrend
from app.backtest.vwap import backtest_paper as backtest_vwap
from app.config import settings
from app.db import async_session
from app.exchange.base import MarketAdapter
from app.executors.trend import REGIME_ASSET
from app.feature_engine.backfill import backfill_features, candle_time_range
from app.market_data.collector import (
    FUNDING_COVERAGE_TOLERANCE,
    backfill_candles,
    backfill_funding,
)
from app.papers.models import AVERAGING_HEDGE, AVERAGING_KINDS, HEDGE_ASSET, Paper

logger = logging.getLogger(__name__)

POLL_SECONDS = 5
# Executors with a backtest (the others are ready after the backfill).
BACKTESTS: dict[str, Callable[[Paper, datetime | None], Awaitable[object]]] = {
    "vwap": backtest_vwap,
    "regime": backtest_regime,
    "supertrend": backtest_supertrend,
}


def backtest_of(paper: Paper) -> Callable[[Paper, datetime | None], Awaitable[object]] | None:
    """An averaging (hedge) paper's backtest replays its executor's entries
    (if that executor has a backtest); the others run their executor's."""
    if paper.kind in AVERAGING_KINDS:
        return backtest_averaging if paper.executor in BACKTESTS else None
    return BACKTESTS.get(paper.executor)


async def _set(paper_id: int, status: str | None, error: str | None = None) -> None:
    async with async_session() as session, session.begin():
        paper = await session.get(Paper, paper_id)
        if paper is not None:
            paper.prep_status, paper.prep_error = status, error
            paper.updated_at = datetime.now(UTC)


class NotListed(Exception):
    """The paper's coin isn't a perpetual of the market-data provider."""


async def _backfill(adapter: MarketAdapter, paper: Paper) -> None:
    if not adapter.is_listed(paper.asset):
        raise NotListed(f"{paper.asset} isn't listed by the market-data provider")
    end = datetime.now(UTC)
    start_ms = int((end - timedelta(days=settings.backfill_days)).timestamp() * 1000)
    end_ms = int(end.timestamp() * 1000)
    assets = [paper.asset]
    if paper.executor == "trend" and paper.asset != REGIME_ASSET:
        assets.append(REGIME_ASSET)
    if paper.kind == AVERAGING_HEDGE:
        assets.append(HEDGE_ASSET)
    for asset in assets:
        await backfill_candles(adapter, asset, paper.timeframe, start_ms, end_ms)
    await backfill_funding(
        adapter, paper.asset, start_ms, end_ms, coverage_tolerance=FUNDING_COVERAGE_TOLERANCE
    )
    time_range = await candle_time_range(paper.asset, paper.timeframe)
    if time_range is None:
        raise RuntimeError(f"no {paper.timeframe} candles for {paper.asset}")
    await backfill_features(paper.asset, *time_range, paper.timeframe)


async def prepare(adapter: MarketAdapter, paper: Paper) -> None:
    try:
        if paper.prep_status == "backfilling":
            logger.info("paper %d (%s %s): backfilling", paper.id, paper.asset, paper.timeframe)
            await _backfill(adapter, paper)
            backtest = backtest_of(paper)
            if backtest is None:
                await _set(paper.id, None)
                logger.info("paper %d ready", paper.id)
                return
            await _set(paper.id, "backtesting")
        backtest = backtest_of(paper)
        assert backtest is not None  # only a paper with a backtest is set to backtesting
        logger.info("paper %d: backtesting", paper.id)
        await backtest(paper, None)
        await _set(paper.id, None)
        logger.info("paper %d ready", paper.id)
    except NotListed as exc:
        logger.warning("paper %d: %s", paper.id, exc)
        await _set(paper.id, "failed", str(exc))
    except Exception as exc:
        logger.exception("paper %d: preparation failed", paper.id)
        await _set(paper.id, "failed", str(exc)[:500])


async def run_prep_loop(adapter: MarketAdapter) -> None:
    """Prepares papers one at a time, oldest first."""
    while True:
        try:
            async with async_session() as session:
                paper = await session.scalar(
                    select(Paper)
                    .where(Paper.prep_status.in_(("backfilling", "backtesting")))
                    .order_by(Paper.id)
                    .limit(1)
                )
            if paper is not None:
                await prepare(adapter, paper)
                continue
        except Exception:
            logger.exception("paper prep loop failed")
        await asyncio.sleep(POLL_SECONDS)
