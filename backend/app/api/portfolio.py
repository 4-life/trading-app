"""The dashboard's cards and positions table for one mode - see
docs/dashboard.md. Live reads the Hyperliquid account; without the live
keys (or when it can't be read) it answers `live_data: false`."""

import logging
from datetime import datetime
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Query
from pydantic import BaseModel
from sqlalchemy import func, select

from app.db import async_session
from app.execution_engine.demo import unrealized_pnl
from app.execution_engine.live import LiveAccount, LiveClient, live_client
from app.execution_engine.models import DemoBalance, Order, Position, TradingDecision
from app.market_data.collector import PRICE_INTERVAL
from app.market_data.models import Candle

router = APIRouter()
logger = logging.getLogger(__name__)

CLOSED_POSITIONS_LIMIT = 200
# Display price: the latest 1m candle - collected for every asset.


class Stats(BaseModel):
    equity_usd: Decimal
    available_balance_usd: Decimal
    open_positions: int
    exposure_usd: Decimal
    total_pnl_usd: Decimal
    unrealized_pnl_usd: Decimal
    realized_pnl_usd: Decimal


class OpenPositionOut(BaseModel):
    id: int
    paper_id: int
    mode: str
    asset: str
    direction: str
    size: Decimal
    entry_price: Decimal
    current_price: Decimal | None
    unrealized_pnl_usd: Decimal | None
    exposure_usd: Decimal | None
    leverage: Decimal
    # Margin put into the position - the basis for PnL percentages.
    margin_usd: Decimal
    stop_loss_price: Decimal | None
    take_profit_price: Decimal | None
    opened_at: datetime


class ClosedPositionOut(BaseModel):
    id: int
    paper_id: int
    mode: str
    asset: str
    direction: str
    size: Decimal
    entry_price: Decimal
    close_price: Decimal | None
    margin_usd: Decimal
    realized_pnl_usd: Decimal | None
    exit_reason: str | None
    opened_at: datetime
    closed_at: datetime


class PortfolioOut(BaseModel):
    mode: str
    live_data: bool
    stats: Stats | None
    open_positions: list[OpenPositionOut]
    closed_positions: list[ClosedPositionOut]


async def _prices(assets: set[str]) -> dict[str, Decimal]:
    prices: dict[str, Decimal] = {}
    async with async_session() as session:
        for asset in assets:
            close = await session.scalar(
                select(Candle.close)
                .where(Candle.asset == asset, Candle.interval == PRICE_INTERVAL)
                .order_by(Candle.open_time.desc())
                .limit(1)
            )
            if close is not None:
                prices[asset] = close
    return prices


async def exit_levels(position_ids: list[int]) -> dict[int, tuple[Decimal | None, Decimal | None]]:
    """SL/TP prices of the entry decision that opened each position."""
    if not position_ids:
        return {}
    async with async_session() as session:
        rows = await session.execute(
            select(
                Order.position_id,
                TradingDecision.stop_loss_price,
                TradingDecision.take_profit_price,
            )
            .join(TradingDecision, TradingDecision.order_id == Order.id)
            .where(Order.position_id.in_(position_ids), TradingDecision.signal == "enter")
        )
        return {pid: (sl, tp) for pid, sl, tp in rows.all() if pid is not None}


@router.get("/portfolio", response_model=PortfolioOut)
async def portfolio(mode: Literal["demo", "live"] = Query(default="demo")) -> PortfolioOut:
    live_account: LiveAccount | None = None
    client: LiveClient | None = None
    if mode == "live":
        try:
            client = await live_client()
            live_account = await client.account() if client else None
        except Exception:
            logger.exception("could not read the live Hyperliquid account")
        if client is None or live_account is None:
            return PortfolioOut(
                mode=mode, live_data=False, stats=None, open_positions=[], closed_positions=[]
            )

    async with async_session() as session:
        balance = await session.get(DemoBalance, 1)
        open_rows = (
            await session.scalars(
                select(Position)
                .where(Position.mode == mode, Position.closed_at.is_(None))
                .order_by(Position.opened_at.desc())
            )
        ).all()
        closed_rows = (
            await session.scalars(
                select(Position)
                .where(Position.mode == mode, Position.closed_at.is_not(None))
                .order_by(Position.closed_at.desc())
                .limit(CLOSED_POSITIONS_LIMIT)
            )
        ).all()
        realized = await session.scalar(
            select(func.coalesce(func.sum(Position.realized_pnl_usd), 0)).where(
                Position.mode == mode, Position.closed_at.is_not(None)
            )
        )

    assets = {p.asset for p in open_rows}
    if client is not None:
        prices = {a: await client.mid_price(a) for a in assets}
    else:
        prices = await _prices(assets)
    levels = await exit_levels([p.id for p in open_rows])
    if live_account is not None:
        cash = live_account.withdrawable
    else:
        cash = balance.balance_usd if balance is not None else Decimal(0)

    open_out: list[OpenPositionOut] = []
    unrealized_total = Decimal(0)
    exposure_total = Decimal(0)
    margin_total = Decimal(0)
    for p in open_rows:
        price = prices.get(p.asset)
        pnl = unrealized_pnl(p.direction, p.entry_price, price, p.size) if price else None
        exposure = p.size * price if price else None
        unrealized_total += pnl or 0
        exposure_total += exposure or 0
        margin_total += p.margin_usd
        sl, tp = levels.get(p.id, (None, None))
        open_out.append(
            OpenPositionOut(
                id=p.id,
                paper_id=p.paper_id,
                mode=p.mode,
                asset=p.asset,
                direction=p.direction,
                size=p.size,
                entry_price=p.entry_price,
                current_price=price,
                unrealized_pnl_usd=pnl,
                exposure_usd=exposure,
                leverage=p.leverage,
                margin_usd=p.margin_usd,
                stop_loss_price=sl,
                take_profit_price=tp,
                opened_at=p.opened_at,
            )
        )

    realized_total = Decimal(realized or 0)
    stats = Stats(
        # Live: Hyperliquid's account value. Demo: cash + the margin
        # reserved in open positions + their unrealized PnL.
        equity_usd=(
            live_account.account_value
            if live_account is not None
            else cash + margin_total + unrealized_total
        ),
        available_balance_usd=cash,
        open_positions=len(open_rows),
        exposure_usd=exposure_total,
        total_pnl_usd=realized_total + unrealized_total,
        unrealized_pnl_usd=unrealized_total,
        realized_pnl_usd=realized_total,
    )
    closed_out = [
        ClosedPositionOut(
            id=p.id,
            paper_id=p.paper_id,
            mode=p.mode,
            asset=p.asset,
            direction=p.direction,
            size=p.size,
            entry_price=p.entry_price,
            close_price=p.close_price,
            # Realized PnL covers every partial close - divide by the whole margin.
            margin_usd=p.initial_margin_usd,
            realized_pnl_usd=p.realized_pnl_usd,
            exit_reason=p.exit_reason,
            opened_at=p.opened_at,
            closed_at=p.closed_at,
        )
        for p in closed_rows
        if p.closed_at is not None
    ]
    return PortfolioOut(
        mode=mode, live_data=True, stats=stats, open_positions=open_out, closed_positions=closed_out
    )
