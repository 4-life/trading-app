"""The order queue (trading_decisions): executors, manual close and the risk
engine add `pending` requests here - see docs/strategy-executor.md#order-flow."""

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Literal

from sqlalchemy import select

from app.db import async_session
from app.execution_engine.models import TradingDecision
from app.feature_engine.models import Feature
from app.papers.models import Paper

logger = logging.getLogger(__name__)

Direction = Literal["long", "short"]


@dataclass(frozen=True)
class Signal:
    signal: Literal["enter", "exit", "add"]  # add: a unit added to the open position
    direction: Direction
    # Cause token, e.g. "flat_entry", "stop_loss_2pct" - see each strategy's doc.
    reason: str
    stop_loss_price: Decimal | None = None
    take_profit_price: Decimal | None = None
    # Exits only: share of the open position to close (e.g. 0.5); None = all.
    close_fraction: Decimal | None = None


async def _feature_snapshot(asset: str, timeframe: str) -> dict[str, float]:
    async with async_session() as session:
        latest = await session.scalar(
            select(Feature.computed_at)
            .where(Feature.asset == asset, Feature.interval == timeframe)
            .order_by(Feature.computed_at.desc())
            .limit(1)
        )
        if latest is None:
            return {}
        rows = await session.execute(
            select(Feature.name, Feature.value).where(
                Feature.asset == asset, Feature.interval == timeframe, Feature.computed_at == latest
            )
        )
        return {name: float(value) for name, value in rows.all()}


async def queue_decision(paper: Paper, signal: Signal, price: Decimal | None) -> int:
    """Inserts a `pending` decision (an order request) and returns its id.
    Raises sqlalchemy's IntegrityError if the paper already has one in
    flight."""
    decision = TradingDecision(
        decided_at=datetime.now(UTC),
        paper_id=paper.id,
        mode=paper.mode,
        asset=paper.asset,
        feature_snapshot=await _feature_snapshot(paper.asset, paper.timeframe),
        signal=signal.signal,
        direction=signal.direction,
        reason=signal.reason,
        entry_price=price,
        stop_loss_price=signal.stop_loss_price,
        take_profit_price=signal.take_profit_price,
        close_fraction=signal.close_fraction,
        outcome="pending",
    )
    async with async_session() as session:
        session.add(decision)
        await session.commit()
    logger.info(
        "paper %d (%s %s %s): queued %s %s - %s",
        paper.id,
        paper.asset,
        paper.timeframe,
        paper.mode,
        signal.signal,
        signal.direction,
        signal.reason,
    )
    return decision.id
