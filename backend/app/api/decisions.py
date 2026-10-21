"""The trading log (docs/dashboard.md#trading-log): the Trading Decision
Log, newest first, paginated."""

from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from fastapi import APIRouter, Query
from pydantic import BaseModel
from sqlalchemy import func, select

from app.db import async_session
from app.execution_engine.models import Order, Position, TradingDecision

router = APIRouter()


class DecisionOut(BaseModel):
    id: int
    decided_at: datetime
    paper_id: int
    mode: str
    asset: str
    signal: str
    direction: str
    reason: str
    outcome: str
    risk_approved: bool | None
    risk_reason: str | None
    position_size_usd: Decimal | None
    entry_price: Decimal | None
    stop_loss_price: Decimal | None
    take_profit_price: Decimal | None
    order_id: int | None
    feature_snapshot: dict[str, Any]
    # Its filled order, if any: price, size (coins) and fee.
    fill_price: Decimal | None = None
    fill_size: Decimal | None = None
    fee_usd: Decimal | None = None
    # An exit: its position's average entry, and whether this order closed
    # it - then the position's whole realized PnL and the margin put in
    # (a partial close's own PnL isn't stored).
    position_entry_price: Decimal | None = None
    closed_position: bool = False
    realized_pnl_usd: Decimal | None = None
    margin_usd: Decimal | None = None

    model_config = {"from_attributes": True}


class DecisionPage(BaseModel):
    items: list[DecisionOut]
    total: int
    page: int
    page_size: int


def _out(
    decision: TradingDecision, order: Order | None, position: Position | None, last: int | None
) -> DecisionOut:
    out = DecisionOut.model_validate(decision)
    if order is None or order.fill_price is None:
        return out
    out.fill_price, out.fill_size, out.fee_usd = order.fill_price, order.size, order.fee_usd
    if decision.signal == "exit" and position is not None:
        out.position_entry_price = position.entry_price
        out.closed_position = position.closed_at is not None and last == order.id
        if out.closed_position:
            out.realized_pnl_usd = position.realized_pnl_usd
            out.margin_usd = position.initial_margin_usd
    return out


@router.get("/decisions", response_model=DecisionPage)
async def get_decisions(
    mode: Literal["demo", "live"] | None = Query(default=None),
    asset: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=500),
) -> DecisionPage:
    filters = []
    if mode is not None:
        filters.append(TradingDecision.mode == mode)
    if asset is not None:
        filters.append(TradingDecision.asset == asset)
    # The order that closed a closed position: its last.
    last_order = (
        select(Order.position_id, func.max(Order.id).label("order_id"))
        .group_by(Order.position_id)
        .subquery()
    )
    async with async_session() as session:
        total = await session.scalar(select(func.count(TradingDecision.id)).where(*filters))
        rows = (
            await session.execute(
                select(TradingDecision, Order, Position, last_order.c.order_id)
                .outerjoin(Order, Order.id == TradingDecision.order_id)
                .outerjoin(Position, Position.id == Order.position_id)
                .outerjoin(last_order, last_order.c.position_id == Position.id)
                .where(*filters)
                .order_by(TradingDecision.decided_at.desc(), TradingDecision.id.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).all()
    return DecisionPage(
        items=[_out(d, o, p, last) for d, o, p, last in rows],
        total=total or 0,
        page=page,
        page_size=page_size,
    )
