"""The dashboard's position buttons.

- Close: queues an exit request for one open position. It goes through the
  same order queue as any executor exit (risk engine, then execution engine)
  and is logged with reason `manual_close`; once it's placed the paper is
  disabled (app/execution_engine/engine.py) - or, closing only, it's
  `manual_close_only` and the paper keeps running. Doesn't touch the
  auto-trading switch.
- Doesn't exist: the owner already closed a live position on Hyperliquid
  (or Hyperliquid liquidated it) - record it closed at the price they
  enter, reason `closed_on_exchange`. Nothing is sent to the exchange. The
  paper is disabled with it, as by a manual close.
"""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Literal, cast

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.db import async_session
from app.execution_engine.engine import (
    MANUAL_CLOSE,
    MANUAL_CLOSE_ONLY,
    entry_fee_share,
    update_profitability,
)
from app.execution_engine.models import IN_FLIGHT_OUTCOMES, Position, TradingDecision
from app.executors.base import latest_price
from app.notifications.trades import notify_closed_on_exchange
from app.order_queue import Signal, queue_decision
from app.papers.models import Paper
from app.system.exchange_api import taker_fee_rate

CLOSED_ON_EXCHANGE = "closed_on_exchange"
CLOSED_ON_EXCHANGE_STOP = "position closed on the exchange"


class NoOpenPosition(Exception):
    pass


class OrderInFlight(Exception):
    pass


class NotLive(Exception):
    pass


async def request_manual_close(position_id: int, disable_paper: bool = True) -> int:
    """Returns the queued decision's id. `disable_paper`: the paper stops
    once the close is placed; else it keeps running."""
    async with async_session() as session:
        position = await session.get(Position, position_id)
        if position is None or position.closed_at is not None:
            raise NoOpenPosition(f"no open position {position_id}")
        paper = await session.scalar(select(Paper).where(Paper.id == position.paper_id))
    if paper is None:
        raise NoOpenPosition(f"position {position_id} has no paper")

    direction = cast(Literal["long", "short"], position.direction)
    signal = Signal("exit", direction, MANUAL_CLOSE if disable_paper else MANUAL_CLOSE_ONLY)
    try:
        return await queue_decision(paper, signal, await latest_price(paper.asset, paper.timeframe))
    except IntegrityError as exc:
        raise OrderInFlight(f"paper {paper.id} already has an order in flight") from exc


async def record_closed_on_exchange(position_id: int, close_price: Decimal) -> None:
    """Realized PnL: the price move, minus the entry fee and an estimated
    taker fee for the exit (the actual one was paid outside the app)."""
    async with async_session() as session, session.begin():
        position = await session.scalar(
            select(Position)
            .where(Position.id == position_id, Position.closed_at.is_(None))
            .with_for_update()
        )
        if position is None:
            raise NoOpenPosition(f"no open position {position_id}")
        if position.mode != "live":
            raise NotLive("only live positions can be closed on the exchange")
        in_flight = await session.scalar(
            select(TradingDecision.id)
            .where(
                TradingDecision.paper_id == position.paper_id,
                TradingDecision.outcome.in_(IN_FLIGHT_OUTCOMES),
            )
            .limit(1)
        )
        if in_flight is not None:
            raise OrderInFlight(f"paper {position.paper_id} has an order in flight")
        sign = 1 if position.direction == "long" else -1
        pnl = sign * (close_price - position.entry_price) * position.size
        pnl -= close_price * position.size * await taker_fee_rate()
        pnl -= await entry_fee_share(session, position, position.size)
        position.realized_pnl_usd = (position.realized_pnl_usd or Decimal(0)) + pnl
        position.close_price = close_price
        position.closed_at = datetime.now(UTC)
        position.exit_reason = CLOSED_ON_EXCHANGE
        await session.flush()
        paper = await session.get(Paper, position.paper_id)
        if paper is not None:
            await update_profitability(session, paper, "live")
            paper.enabled = False
            paper.disabled_by = "owner"
            paper.disabled_reason = CLOSED_ON_EXCHANGE_STOP
            paper.updated_at = datetime.now(UTC)
    await notify_closed_on_exchange(position_id, position.size, close_price)
