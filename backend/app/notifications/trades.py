"""Telegram message on every position open and close (docs/watchdog.md#alerting):
what happened, and the mode's budget and today's realized PnL after it.
Sent after the trade is committed; never raises - a failed message must not
break trading."""

import logging
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import func, select

from app.budget_allocator import free_cash, mode_total
from app.db import async_session
from app.execution_engine.models import Order, Position, TradingDecision
from app.executors.position_management import AVERAGE_DOWN, SIGNAL_ADD
from app.notifications.telegram import send_telegram
from app.papers.models import Paper

logger = logging.getLogger(__name__)

UP = "📈"  # a long open
DOWN = "📉"  # a short open
PROFIT = "📈 🚀"  # a close with PnL >= 0
LOSS = "📉 ❌"  # a close at a loss


def money(value: Decimal | None, signed: bool = False) -> str:
    if value is None:
        return "n/a"
    sign = ("+" if value >= 0 else "-") if signed else ("-" if value < 0 else "")
    return f"{sign}${abs(value):,.2f}"


def price(value: Decimal | None) -> str:
    return "n/a" if value is None else f"{value:,.4f}" if value < 1 else f"{value:,.2f}"


def amount(value: Decimal) -> str:
    """A position or order size: at most 4 decimals."""
    return f"{value:,.4f}".rstrip("0").rstrip(".")


def leverage(value: Decimal) -> str:
    """At most one decimal - an averaging position's leverage is its adds'
    blend (27.97 after ×5 adds on a ×30 entry): ×28; 10 not 1E+1."""
    return f"{round(value, 1).normalize():f}"


def trade_message(
    *,
    opened: bool,
    paper: Paper,
    position: Position,
    order_price: Decimal | None,
    size: Decimal,
    reason: str,
    stop_loss: Decimal | None,
    take_profit: Decimal | None,
    balance: Decimal | None,
    free: Decimal | None,
    open_margin: Decimal,
    today: Decimal,
) -> str:
    """The message text - pure, so it's testable. The chart mark: an open's
    direction (long up), a close's result (profit up). An averaging paper's
    kind is in the head - it has no SL / TP of its own. `open_margin`: the
    mode's open positions' margin together, this one's included."""
    averaging = paper.kind == "averaging"
    kind = f" {paper.kind}" if averaging else ""
    head = f"{paper.asset} {paper.timeframe} {paper.executor}{kind} #{paper.id}"
    if opened:
        mark = UP if position.direction == "long" else DOWN
        # An add (averaging down) grows the open position; the margin is the whole position's.
        label = "ADD" if reason in (AVERAGE_DOWN, SIGNAL_ADD) else "OPEN"
        lines = [
            f"{mark} {label} {head}",
            f"{position.direction} {amount(size)}",
            "",
            f"{price(order_price)} · position margin {money(position.margin_usd)} "
            f"×{leverage(position.leverage)} · {reason}",
        ]
        if not averaging:
            lines += ["", f"SL {price(stop_loss)} · TP {price(take_profit)}"]
    else:
        pnl = position.realized_pnl_usd or Decimal(0)
        margin = position.initial_margin_usd or position.margin_usd
        pct = f" ({pnl / margin * 100:+.1f}% of margin)" if margin else ""
        partial = position.closed_at is None
        lines = [
            f"{PROFIT if pnl >= 0 else LOSS} {'PARTIAL CLOSE' if partial else 'CLOSE'} {head}",
            f"{position.direction} {amount(size)}",
            "",
            f"{price(position.entry_price)} → {price(order_price)} · {reason}",
            "",
            f"PnL {money(pnl, signed=True)}{pct}{' so far' if partial else ''}",
        ]
    lines += [
        "",
        f"{'🟢' if today >= 0 else '🔴'} balance {money(balance)} · free {money(free)} "
        f"· open margin {money(open_margin)} · today {money(today, signed=True)}",
    ]
    return "\n".join([f"[{position.mode.upper()}]", *lines])


async def _send(
    position_id: int, order_price: Decimal | None, size: Decimal, opened: bool, reason: str
) -> None:
    async with async_session() as session:
        position = await session.get(Position, position_id)
        paper = await session.get(Paper, position.paper_id) if position else None
        if position is None or paper is None:
            return
        entry = await session.scalar(
            select(TradingDecision)
            .where(
                TradingDecision.paper_id == paper.id,
                TradingDecision.signal == "enter",
                TradingDecision.outcome == "placed",
                TradingDecision.decided_at <= position.opened_at,
            )
            .order_by(TradingDecision.decided_at.desc())
            .limit(1)
        )
        day_start = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
        today = await session.scalar(
            select(func.coalesce(func.sum(Position.realized_pnl_usd), 0)).where(
                Position.mode == position.mode, Position.closed_at >= day_start
            )
        )
        open_margin = await session.scalar(
            select(func.coalesce(func.sum(Position.margin_usd), 0)).where(
                Position.mode == position.mode, Position.closed_at.is_(None)
            )
        )
    text = trade_message(
        opened=opened,
        paper=paper,
        position=position,
        order_price=order_price,
        size=size,
        reason=reason,
        stop_loss=entry.stop_loss_price if entry else None,
        take_profit=entry.take_profit_price if entry else None,
        balance=await mode_total(position.mode),
        free=await free_cash(position.mode),
        open_margin=Decimal(open_margin or 0),
        today=Decimal(today or 0),
    )
    await send_telegram(text)


async def notify_order(order_id: int) -> None:
    """For a filled order: the open, or the (partial) close, it made."""
    try:
        async with async_session() as session:
            order = await session.get(Order, order_id)
            if order is None or order.position_id is None:
                return
            position = await session.get(Position, order.position_id)
            decision = await session.scalar(
                select(TradingDecision).where(TradingDecision.order_id == order_id).limit(1)
            )
        if position is None:
            return
        opened = (position.direction == "long") == (order.side == "buy")
        reason = decision.reason if decision else ""
        await _send(position.id, order.fill_price, order.size, opened, reason)
    except Exception:
        logger.exception("trade notification for order %d failed", order_id)


async def notify_closed_on_exchange(position_id: int, size: Decimal, close_price: Decimal) -> None:
    """A live position the owner recorded as closed on the exchange."""
    try:
        await _send(position_id, close_price, size, False, "closed on the exchange")
    except Exception:
        logger.exception("trade notification for position %d failed", position_id)
