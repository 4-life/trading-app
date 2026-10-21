import logging
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import delete, func, select, update

from app.db import async_session
from app.execution_engine.models import (
    DEMO_STARTING_BALANCE_USD,
    DemoBalance,
    EquitySnapshot,
    Order,
    Position,
    TradingDecision,
)
from app.papers.models import Paper

logger = logging.getLogger(__name__)


async def reset_demo_state() -> dict[str, int]:
    """Demo reset (docs/papers.md#demo-reset): deletes every demo position
    (open and closed), order, trading decision and equity snapshot, sets the
    demo balance back to its starting value and every paper's
    profitability_demo to 0. Live state is never touched."""
    async with async_session() as session:
        positions = await session.scalar(
            select(func.count(Position.id)).where(Position.mode == "demo")
        )
        orders = await session.scalar(select(func.count(Order.id)).where(Order.mode == "demo"))
        decisions = await session.scalar(
            select(func.count(TradingDecision.id)).where(TradingDecision.mode == "demo")
        )
        # FK order: decisions -> orders -> positions.
        await session.execute(delete(TradingDecision).where(TradingDecision.mode == "demo"))
        await session.execute(delete(Order).where(Order.mode == "demo"))
        await session.execute(delete(Position).where(Position.mode == "demo"))
        await session.execute(delete(EquitySnapshot).where(EquitySnapshot.mode == "demo"))
        await session.execute(
            update(DemoBalance).values(
                balance_usd=DEMO_STARTING_BALANCE_USD, updated_at=datetime.now(UTC)
            )
        )
        await session.execute(update(Paper).values(profitability_demo=Decimal(0)))
        await session.commit()

    logger.info(
        "demo reset: deleted %d position(s), %d order(s), %d decision(s)",
        positions or 0,
        orders or 0,
        decisions or 0,
    )
    return {
        "positions_deleted": positions or 0,
        "orders_deleted": orders or 0,
        "decisions_deleted": decisions or 0,
    }
