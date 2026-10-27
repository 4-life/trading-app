"""Execution engine: takes `approved` requests off the order queue
(trading_decisions) and marks each `placed` or `failed`, and liquidates
positions below the maintenance margin - see docs/execution-engine.md. Demo
requests are filled in the database at the Hyperliquid market price; live
requests are sent to Hyperliquid (app/execution_engine/live.py)."""

import logging
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import async_session
from app.exchange.base import MarketAdapter
from app.execution_engine.demo import (
    Quote,
    close_fill,
    close_side,
    funding_paid,
    grow,
    liquidation_due,
    open_fill,
    open_side,
    profitability_pct,
)
from app.execution_engine.live import LiveClient, LiveOrderError, live_client, round_size
from app.execution_engine.models import DemoBalance, Order, Position, TradingDecision
from app.executors.position_management import add_terms, stops_paper
from app.market_data.models import FundingRate
from app.notifications.alerts import alert
from app.notifications.trades import notify_order
from app.papers.models import Paper
from app.system.auto_open import is_auto_open_enabled
from app.system.exchange_api import taker_fee_rate
from app.watchdog.redis_client import set_heartbeat

logger = logging.getLogger(__name__)

LIQUIDATION = "liquidation"
TAKE_PROFIT_STOP = "take-profit reached - enable it again at the next bottom"
# The dashboard's Close (app/execution_engine/manual_close.py): the paper stops with it.
MANUAL_CLOSE = "manual_close"
MANUAL_CLOSE_STOP = "position closed manually"
SERVICE_NAME = "execution-engine"


def _stop_reason(paper: Paper, reason: str) -> str | None:
    """Why closing the whole position disables the paper - the owner's
    manual close, or an averaging paper's take-profit (stops_paper); None:
    it keeps running."""
    if reason == MANUAL_CLOSE:
        return MANUAL_CLOSE_STOP
    if stops_paper(paper, reason):
        return TAKE_PROFIT_STOP
    return None


class FillError(Exception):
    """The request can't be filled - it's marked `failed` with this reason."""


class ProviderRejected(FillError):
    """The exchange refused or didn't fill the order (e.g. a coin it doesn't
    list) - marked `rejected_by_provider`."""


async def _approved_ids() -> list[int]:
    async with async_session() as session:
        rows = await session.scalars(
            select(TradingDecision.id)
            .where(TradingDecision.outcome == "approved")
            .order_by(TradingDecision.decided_at, TradingDecision.id)
        )
        return list(rows.all())


async def _funding_rates(
    session: AsyncSession, asset: str, since: datetime
) -> list[tuple[datetime, Decimal]]:
    rows = await session.execute(
        select(FundingRate.exchange_timestamp, FundingRate.funding_rate).where(
            FundingRate.asset == asset, FundingRate.exchange_timestamp > since
        )
    )
    return [(ts, rate) for ts, rate in rows.all()]


async def _locked_balance(session: AsyncSession) -> DemoBalance:
    balance = await session.scalar(select(DemoBalance).with_for_update())
    if balance is None:
        raise FillError("demo balance row is missing")
    return balance


async def update_profitability(session: AsyncSession, paper: Paper, mode: str) -> None:
    """Realized PnL / margin used of the paper's closed positions in `mode`,
    as a percentage - see docs/papers.md."""
    realized, margin = (
        await session.execute(
            select(
                func.coalesce(func.sum(Position.realized_pnl_usd), 0),
                func.coalesce(func.sum(Position.initial_margin_usd), 0),
            ).where(
                Position.paper_id == paper.id,
                Position.mode == mode,
                Position.closed_at.is_not(None),
            )
        )
    ).one()
    value = profitability_pct(Decimal(realized), Decimal(margin))
    if mode == "demo":
        paper.profitability_demo = value
    else:
        paper.profitability_live = value
    paper.updated_at = datetime.now(UTC)


async def _enter(
    session: AsyncSession, decision: TradingDecision, paper: Paper, quote: Quote
) -> int:
    if not decision.position_size_usd or decision.position_size_usd <= 0:
        raise FillError("no position size from the risk engine")
    open_position = await session.scalar(
        select(Position.id).where(Position.paper_id == paper.id, Position.closed_at.is_(None))
    )
    if open_position is not None:
        raise FillError("paper already has an open position")
    balance = await _locked_balance(session)

    fee_rate = await taker_fee_rate()
    fill = open_fill(
        decision.direction, decision.position_size_usd, paper.leverage, quote, fee_rate
    )
    if balance.balance_usd < fill.margin_usd + fill.fee_usd:
        raise FillError(
            f"insufficient demo balance: need {fill.margin_usd + fill.fee_usd:.2f}, "
            f"have {balance.balance_usd:.2f}"
        )

    now = datetime.now(UTC)
    position = Position(
        paper_id=paper.id,
        mode="demo",
        asset=paper.asset,
        direction=decision.direction,
        size=fill.size,
        entry_price=fill.price,
        leverage=paper.leverage,
        margin_usd=fill.margin_usd,
        initial_margin_usd=fill.margin_usd,
        peak_price=fill.price,
        opened_at=now,
    )
    session.add(position)
    await session.flush()
    order = Order(
        paper_id=paper.id,
        position_id=position.id,
        mode="demo",
        asset=paper.asset,
        side=open_side(decision.direction),
        size=fill.size,
        fill_price=fill.price,
        fee_usd=fill.fee_usd,
        status="filled",
        created_at=now,
    )
    session.add(order)
    balance.balance_usd -= fill.margin_usd + fill.fee_usd
    balance.updated_at = now
    await session.flush()
    return order.id


async def close_position(
    session: AsyncSession,
    position: Position,
    paper: Paper,
    quote: Quote,
    reason: str,
    client: LiveClient | None,
    fraction: Decimal = Decimal(1),
) -> int:
    """Closes `fraction` of a locked, open position (all of it by default);
    returns the closing order's id. Shared by queued exits and liquidations.
    Demo fills at `quote`'s bid / ask, live on Hyperliquid (`quote` unused)."""
    if not 0 < fraction <= 1:
        raise FillError(f"close fraction must be in (0, 1], got {fraction}")
    if position.mode == "live":
        if client is None:
            raise FillError("no exchange API set")
        return await _close_live(session, position, paper, reason, client, fraction)
    return await _close_demo(session, position, paper, quote, reason, fraction)


async def entry_fee_share(
    session: AsyncSession, position: Position, closed_size: Decimal
) -> Decimal:
    """The part of the entry fees that belongs to `closed_size` - each close
    carries its share of the size opened (the first entry and every add), so
    partial closes add up to the fees."""
    fees, size = (
        await session.execute(
            select(func.coalesce(func.sum(Order.fee_usd), 0), func.sum(Order.size)).where(
                Order.position_id == position.id, Order.side == open_side(position.direction)
            )
        )
    ).one()
    if not size:
        return Decimal(0)
    return Decimal(fees) * closed_size / Decimal(size)


async def _close_demo(
    session: AsyncSession,
    position: Position,
    paper: Paper,
    quote: Quote,
    reason: str,
    fraction: Decimal,
) -> int:
    balance = await _locked_balance(session)
    now = datetime.now(UTC)
    size = position.size * fraction
    rates = await _funding_rates(session, paper.asset, position.opened_at)
    funding = funding_paid(
        position.direction, size, position.entry_price, rates, position.opened_at, now
    )
    fill = close_fill(
        position.direction, size, position.entry_price, quote, funding, await taker_fee_rate()
    )
    pnl = fill.settlement_pnl_usd - await entry_fee_share(session, position, size)

    order = Order(
        paper_id=paper.id,
        position_id=position.id,
        mode="demo",
        asset=paper.asset,
        side=close_side(position.direction),
        size=size,
        fill_price=fill.price,
        fee_usd=fill.fee_usd,
        status="filled",
        created_at=now,
    )
    session.add(order)
    margin = position.margin_usd * fraction
    position.close_price = fill.price
    position.realized_pnl_usd = (position.realized_pnl_usd or Decimal(0)) + pnl
    balance.balance_usd += margin + fill.settlement_pnl_usd
    balance.updated_at = now
    if fraction < 1:
        position.size -= size
        position.margin_usd -= margin
    else:
        position.closed_at = now
        position.exit_reason = reason
    await session.flush()
    await update_profitability(session, paper, position.mode)
    return order.id


async def _close_live(
    session: AsyncSession,
    position: Position,
    paper: Paper,
    reason: str,
    client: LiveClient,
    fraction: Decimal,
) -> int:
    """Market (IOC) order on the opposite side for `fraction` of the
    position. A partial close (or fill) reduces the position and leaves it
    open - the next exit signal closes the rest. Funding is settled by
    Hyperliquid on the account, not in realized PnL."""
    is_buy = position.direction == "short"
    size = position.size
    try:
        if fraction < 1:
            size = round_size(position.size * fraction, client.size_decimals(paper.asset))
            if size <= 0:
                raise FillError("partial close size rounds to zero")
        fill = await client.close(paper.asset, is_buy, size)
    except LiveOrderError as exc:
        raise ProviderRejected(str(exc)) from exc
    fee = await client.fee(fill)
    now = datetime.now(UTC)
    order = Order(
        paper_id=paper.id,
        position_id=position.id,
        mode="live",
        asset=paper.asset,
        side=close_side(position.direction),
        size=fill.size,
        fill_price=fill.price,
        fee_usd=fee,
        exchange_order_id=str(fill.order_id),
        status="filled",
        created_at=now,
    )
    session.add(order)
    sign = 1 if position.direction == "long" else -1
    closed_share = min(fill.size / position.size, Decimal(1))
    pnl = sign * (fill.price - position.entry_price) * fill.size - fee
    pnl -= await entry_fee_share(session, position, min(fill.size, position.size))
    position.realized_pnl_usd = (position.realized_pnl_usd or Decimal(0)) + pnl
    position.close_price = fill.price
    if fill.size < position.size:
        position.margin_usd *= 1 - closed_share
        position.size -= fill.size
        logger.warning("position %d: partial close, %s left open", position.id, position.size)
    else:
        position.closed_at = now
        position.exit_reason = reason
    await session.flush()
    await update_profitability(session, paper, "live")
    return order.id


async def _enter_live(
    session: AsyncSession, decision: TradingDecision, paper: Paper, client: LiveClient
) -> int:
    if not decision.position_size_usd or decision.position_size_usd <= 0:
        raise FillError("no position size from the risk engine")
    leverage = int(paper.leverage)
    if leverage != paper.leverage:
        raise FillError("live leverage must be a whole number")
    open_position = await session.scalar(
        select(Position.id).where(Position.paper_id == paper.id, Position.closed_at.is_(None))
    )
    if open_position is not None:
        raise FillError("paper already has an open position")

    try:
        price = await client.mid_price(paper.asset)
        size = round_size(decision.position_size_usd / price, client.size_decimals(paper.asset))
        if size <= 0:
            raise FillError("position size rounds to zero")
        fill = await client.open(paper.asset, decision.direction == "long", size, leverage)
    except LiveOrderError as exc:
        raise ProviderRejected(str(exc)) from exc
    fee = await client.fee(fill)

    now = datetime.now(UTC)
    position = Position(
        paper_id=paper.id,
        mode="live",
        asset=paper.asset,
        direction=decision.direction,
        size=fill.size,
        entry_price=fill.price,
        leverage=paper.leverage,
        margin_usd=fill.price * fill.size / leverage,
        initial_margin_usd=fill.price * fill.size / leverage,
        peak_price=fill.price,
        opened_at=now,
    )
    session.add(position)
    await session.flush()
    order = Order(
        paper_id=paper.id,
        position_id=position.id,
        mode="live",
        asset=paper.asset,
        side=open_side(decision.direction),
        size=fill.size,
        fill_price=fill.price,
        fee_usd=fee,
        exchange_order_id=str(fill.order_id),
        status="filled",
        created_at=now,
    )
    session.add(order)
    await session.flush()
    return order.id


async def _open_for_add(
    session: AsyncSession, paper: Paper, reason: str
) -> tuple[Position, Decimal]:
    """The open position an add grows, and the add's leverage (add_terms)."""
    terms = add_terms(paper, reason)
    if terms is None:
        raise FillError("averaging down is off for this paper")
    position = await session.scalar(
        select(Position)
        .where(Position.paper_id == paper.id, Position.closed_at.is_(None))
        .with_for_update()
    )
    if position is None:
        raise FillError("no open position to add to")
    return position, terms[1]


def _apply_add(position: Position, size: Decimal, price: Decimal, margin: Decimal) -> None:
    grown = grow(position.size, position.entry_price, position.margin_usd, size, price, margin)
    position.size, position.entry_price = grown.size, grown.entry_price
    position.margin_usd, position.leverage = grown.margin_usd, grown.leverage
    # Profitability divides by all the margin put in.
    position.initial_margin_usd += margin


async def _add(session: AsyncSession, decision: TradingDecision, paper: Paper, quote: Quote) -> int:
    """An add in demo: a unit at its leverage (a dip add's add leverage, a
    signal add's paper leverage) grows the open position
    (docs/papers.md#averaging-papers)."""
    if not decision.position_size_usd or decision.position_size_usd <= 0:
        raise FillError("no add size from the risk engine")
    position, leverage = await _open_for_add(session, paper, decision.reason)
    balance = await _locked_balance(session)
    fill = open_fill(
        position.direction, decision.position_size_usd, leverage, quote, await taker_fee_rate()
    )
    if balance.balance_usd < fill.margin_usd + fill.fee_usd:
        raise FillError(
            f"insufficient demo balance: need {fill.margin_usd + fill.fee_usd:.2f}, "
            f"have {balance.balance_usd:.2f}"
        )
    now = datetime.now(UTC)
    _apply_add(position, fill.size, fill.price, fill.margin_usd)
    order = Order(
        paper_id=paper.id,
        position_id=position.id,
        mode="demo",
        asset=paper.asset,
        side=open_side(position.direction),
        size=fill.size,
        fill_price=fill.price,
        fee_usd=fill.fee_usd,
        status="filled",
        created_at=now,
    )
    session.add(order)
    balance.balance_usd -= fill.margin_usd + fill.fee_usd
    balance.updated_at = now
    await session.flush()
    return order.id


async def _add_live(
    session: AsyncSession, decision: TradingDecision, paper: Paper, client: LiveClient
) -> int:
    """Averaging down live: a market order grows the isolated position (it
    takes margin at the position's leverage setting, the paper's leverage),
    then the rest of the add's margin is moved in, so the unit is backed at
    its leverage (a dip add's add leverage; a signal add's is the paper's,
    nothing to move). A failed transfer leaves the unit at the paper's
    leverage - recorded as such, and alerted."""
    if not decision.position_size_usd or decision.position_size_usd <= 0:
        raise FillError("no add size from the risk engine")
    position, leverage = await _open_for_add(session, paper, decision.reason)
    try:
        price = await client.mid_price(paper.asset)
        size = round_size(decision.position_size_usd / price, client.size_decimals(paper.asset))
        if size <= 0:
            raise FillError("add size rounds to zero")
        fill = await client.add(paper.asset, position.direction == "long", size)
    except LiveOrderError as exc:
        raise ProviderRejected(str(exc)) from exc
    notional = fill.price * fill.size
    margin = notional / leverage
    taken = notional / paper.leverage  # by the order itself
    if margin > taken:
        try:
            await client.add_margin(paper.asset, margin - taken)
        except LiveOrderError as exc:
            margin = taken
            logger.warning("paper %d: margin transfer failed: %s", paper.id, exc)
            await alert(
                SERVICE_NAME,
                "warning",
                f"paper {paper.id} {paper.asset}: add filled but the margin transfer failed "
                f"({exc}) - the unit is at {paper.leverage}x",
            )
    fee = await client.fee(fill)
    _apply_add(position, fill.size, fill.price, margin)
    order = Order(
        paper_id=paper.id,
        position_id=position.id,
        mode="live",
        asset=paper.asset,
        side=open_side(position.direction),
        size=fill.size,
        fill_price=fill.price,
        fee_usd=fee,
        exchange_order_id=str(fill.order_id),
        status="filled",
        created_at=datetime.now(UTC),
    )
    session.add(order)
    await session.flush()
    return order.id


async def _exit(
    session: AsyncSession,
    decision: TradingDecision,
    paper: Paper,
    quote: Quote,
    client: LiveClient | None,
) -> int:
    position = await session.scalar(
        select(Position)
        .where(Position.paper_id == paper.id, Position.closed_at.is_(None))
        .with_for_update()
    )
    if position is None:
        raise FillError("no open position to close")
    fraction = decision.close_fraction if decision.close_fraction is not None else Decimal(1)
    return await close_position(session, position, paper, quote, decision.reason, client, fraction)


async def _process(decision_id: int, adapter: MarketAdapter) -> None:
    placed: int | None = None
    stopped: tuple[Paper, str] | None = None  # the paper disabled by this close, and why
    async with async_session() as session, session.begin():
        decision = await session.scalar(
            select(TradingDecision)
            .where(TradingDecision.id == decision_id, TradingDecision.outcome == "approved")
            .with_for_update(skip_locked=True)
        )
        if decision is None:
            return
        paper = await session.get(Paper, decision.paper_id)
        try:
            if paper is None:
                raise FillError("paper not found")
            if decision.mode == "live":
                client = await live_client()
                if client is None:
                    raise FillError("no exchange API set")
                if decision.signal == "enter":
                    order_id = await _enter_live(session, decision, paper, client)
                elif decision.signal == "add":
                    order_id = await _add_live(session, decision, paper, client)
                else:
                    unused = Quote(Decimal(0), Decimal(0))
                    order_id = await _exit(session, decision, paper, unused, client)
            else:
                market = await adapter.get_market_data(paper.asset)
                quote = Quote(market.bid, market.ask)
                if decision.signal == "enter":
                    order_id = await _enter(session, decision, paper, quote)
                elif decision.signal == "add":
                    order_id = await _add(session, decision, paper, quote)
                else:
                    order_id = await _exit(session, decision, paper, quote, None)
        except FillError as exc:
            decision.outcome = (
                "rejected_by_provider" if isinstance(exc, ProviderRejected) else "failed"
            )
            decision.risk_reason = f"{decision.risk_reason or ''} | execution: {exc}".lstrip(" |")
            logger.warning("decision %d failed: %s", decision_id, exc)
            return
        decision.outcome = "placed"
        decision.order_id = placed = order_id
        stop = _stop_reason(paper, decision.reason) if decision.signal == "exit" else None
        if stop is not None:
            still_open = await session.scalar(
                select(Position.id).where(
                    Position.paper_id == paper.id, Position.closed_at.is_(None)
                )
            )
            if still_open is None:  # a partial close keeps it running
                paper.enabled = False
                paper.disabled_by = "owner"  # the owner's close / rule: stop at the take-profit
                paper.disabled_reason = stop
                paper.updated_at = datetime.now(UTC)
                stopped = paper, stop
        logger.info(
            "decision %d placed: paper %d %s %s %s (%s)",
            decision_id,
            paper.id,
            decision.signal,
            decision.direction,
            paper.asset,
            decision.reason,
        )
    if placed is not None:  # committed - now tell the owner
        await notify_order(placed)
    if stopped is not None:
        disabled, why = stopped
        await alert(SERVICE_NAME, "info", f"paper {disabled.id} {disabled.asset}: {why}")


async def _liquidate(
    position_id: int, quote: Quote, source: str, client: LiveClient | None = None
) -> None:
    market_price = quote.mid
    maintenance = Decimal(str(settings.maintenance_margin_pct))
    async with async_session() as session, session.begin():
        position = await session.scalar(
            select(Position)
            .where(Position.id == position_id, Position.closed_at.is_(None))
            .with_for_update(skip_locked=True)
        )
        if position is None or not liquidation_due(
            position.direction,
            position.entry_price,
            position.size,
            position.margin_usd,
            market_price,
            maintenance,
        ):
            return
        paper = await session.get(Paper, position.paper_id)
        if paper is None:
            return
        order_id = await close_position(session, position, paper, quote, LIQUIDATION, client)
        session.add(
            TradingDecision(
                decided_at=datetime.now(UTC),
                paper_id=paper.id,
                mode=position.mode,
                asset=position.asset,
                feature_snapshot={},
                signal="exit",
                direction=position.direction,
                reason=LIQUIDATION,
                risk_approved=True,
                risk_reason=f"liquidated by {source}: below {maintenance:.0%} maintenance margin",
                entry_price=market_price,
                outcome="placed",
                order_id=order_id,
            )
        )
    await notify_order(order_id)
    await alert(
        source,
        "critical",
        f"liquidated paper {position.paper_id} {position.direction} {position.asset} "
        f"at {market_price}",
    )


async def liquidate_breached(adapter: MarketAdapter, source: str) -> None:
    """Force-closes every open position whose remaining margin is at or below
    MAINTENANCE_MARGIN_PCT of its initial margin. Demo positions are priced
    from market data, live ones from the live exchange. Live ones
    are skipped while the live auto-trading switch is off."""
    async with async_session() as session:
        positions = (
            await session.scalars(select(Position).where(Position.closed_at.is_(None)))
        ).all()
    if not await is_auto_open_enabled():
        positions = [p for p in positions if p.mode != "live"]
    maintenance = Decimal(str(settings.maintenance_margin_pct))
    client = await live_client() if any(p.mode == "live" for p in positions) else None
    quotes: dict[tuple[str, str], Quote] = {}
    for position in positions:
        try:
            key = (position.mode, position.asset)
            if key not in quotes:
                if position.mode == "live":
                    if client is None:
                        continue
                    mid = await client.mid_price(position.asset)
                    quotes[key] = Quote(mid, mid)
                else:
                    market = await adapter.get_market_data(position.asset)
                    quotes[key] = Quote(market.bid, market.ask)
            quote = quotes[key]
            if liquidation_due(
                position.direction,
                position.entry_price,
                position.size,
                position.margin_usd,
                quote.mid,
                maintenance,
            ):
                await _liquidate(position.id, quote, source, client)
        except Exception:
            logger.exception("position %d: liquidation check failed", position.id)


async def run_once(adapter: MarketAdapter) -> None:
    await set_heartbeat(SERVICE_NAME)
    await liquidate_breached(adapter, "execution-engine")
    for decision_id in await _approved_ids():
        try:
            await _process(decision_id, adapter)
        except Exception:
            # Left `approved` - retried on the next pass.
            logger.exception("decision %d: execution error", decision_id)
