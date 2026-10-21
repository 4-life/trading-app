"""Budget allocator - a shared library, not a service (docs/budget-allocator.md).

paper_budget = (total - total * BUDGET_RESERVE_PCT) / enabled papers in the mode

`total` is the mode's balance: for demo, the demo cash plus the margin
reserved in open demo positions (read from the database); for live, the
Hyperliquid account value - none when the live keys aren't set."""

from decimal import Decimal

from sqlalchemy import func, select

from app.config import settings
from app.db import async_session
from app.execution_engine.live import live_client
from app.execution_engine.models import DemoBalance, Position
from app.papers.models import TRADING_KINDS, Paper


def paper_budget_from(total_usd: Decimal, enabled_papers: int, reserve_pct: Decimal) -> Decimal:
    if enabled_papers <= 0:
        return Decimal(0)
    return total_usd * (1 - reserve_pct) / enabled_papers


async def mode_total(mode: str) -> Decimal | None:
    """None when the mode's balance can't be read (live without keys)."""
    if mode == "live":
        client = await live_client()
        return (await client.account()).account_value if client else None
    async with async_session() as session:
        balance = await session.get(DemoBalance, 1)
        reserved = await session.scalar(
            select(func.coalesce(func.sum(Position.margin_usd), 0)).where(
                Position.mode == "demo", Position.closed_at.is_(None)
            )
        )
    cash = balance.balance_usd if balance is not None else Decimal(0)
    return cash + Decimal(reserved or 0)


async def free_cash(mode: str) -> Decimal | None:
    """Balance not tied up in positions: demo cash, or live withdrawable."""
    if mode == "live":
        client = await live_client()
        return (await client.account()).withdrawable if client else None
    async with async_session() as session:
        balance = await session.get(DemoBalance, 1)
    return balance.balance_usd if balance is not None else Decimal(0)


async def paper_budget(mode: str) -> Decimal | None:
    total = await mode_total(mode)
    if total is None:
        return None
    async with async_session() as session:
        count = await session.scalar(
            # Scanner papers hold no positions - only the trading kinds split the
            # budget (an averaging paper sizes itself, but its positions use the cash too).
            select(func.count(Paper.id)).where(
                Paper.mode == mode, Paper.enabled.is_(True), Paper.kind.in_(TRADING_KINDS)
            )
        )
    return paper_budget_from(total, count or 0, Decimal(str(settings.budget_reserve_pct)))
