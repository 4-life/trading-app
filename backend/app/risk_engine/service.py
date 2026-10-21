"""Risk-engine service loop - see docs/risk-engine.md. Each pass:

1. decides every `pending` request in the order queue (exits are always
   approved; entries are sized by the budget allocator - or the paper's
   fixed initial size - and checked against the limits; an add, averaging
   down, is sized by the paper and needs free cash);
2. records each mode's equity (once a minute) for drawdown / daily loss;
3. disables papers whose realized loss reached PAPER_LOSS_DISABLE_PCT of
   their budget;
4. liquidates in the execution engine's place if its heartbeat is stale.
"""

import logging
import time
from datetime import UTC, datetime
from datetime import time as dtime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.backtest.models import OPEN_AT_END, BacktestTrade
from app.backtest.stats import max_drawdown
from app.budget_allocator import free_cash, mode_total, paper_budget
from app.config import settings
from app.db import async_session
from app.exchange.base import MarketAdapter
from app.execution_engine.demo import unrealized_pnl
from app.execution_engine.engine import SERVICE_NAME as EXECUTION_ENGINE
from app.execution_engine.engine import liquidate_breached
from app.execution_engine.models import (
    IN_FLIGHT_OUTCOMES,
    DemoBalance,
    EquitySnapshot,
    Position,
    TradingDecision,
)
from app.executors.position_management import AVERAGE_DOWN, add_terms
from app.market_data.collector import PRICE_INTERVAL
from app.market_data.models import Candle
from app.notifications.alerts import alert
from app.papers.models import AVERAGING_KINDS, Paper
from app.risk_engine.blocks import block_paper, is_entry_blocked, unblock_paper
from app.risk_engine.engine import evaluate
from app.risk_engine.models import Position as RiskPosition
from app.risk_engine.models import ProposedOrder
from app.system.exchange_api import taker_fee_rate
from app.system.models import RiskEvent
from app.watchdog.redis_client import heartbeat_age_seconds, is_kill_switch_active

logger = logging.getLogger(__name__)

EQUITY_SNAPSHOT_SECONDS = 60


class Rejected(Exception):
    pass


async def _price(session: AsyncSession, asset: str) -> Decimal | None:
    price: Decimal | None = await session.scalar(
        select(Candle.close)
        .where(Candle.asset == asset, Candle.interval == PRICE_INTERVAL)
        .order_by(Candle.open_time.desc())
        .limit(1)
    )
    return price


async def mode_equity(mode: str) -> Decimal | None:
    """Demo: cash + reserved margin + unrealized PnL of open positions.
    Live: the Hyperliquid account value (None without live keys)."""
    if mode == "live":
        return await mode_total("live")
    async with async_session() as session:
        balance = await session.get(DemoBalance, 1)
        positions = (
            await session.scalars(
                select(Position).where(Position.mode == mode, Position.closed_at.is_(None))
            )
        ).all()
        equity = balance.balance_usd if balance is not None else Decimal(0)
        for p in positions:
            price = await _price(session, p.asset)
            equity += p.margin_usd
            if price is not None:
                equity += unrealized_pnl(p.direction, p.entry_price, price, p.size)
    return equity


async def _peak_and_day_start(mode: str) -> tuple[Decimal | None, Decimal | None]:
    day_start = datetime.combine(datetime.now(UTC).date(), dtime(0), tzinfo=UTC)
    async with async_session() as session:
        peak = await session.scalar(
            select(func.max(EquitySnapshot.equity_usd)).where(
                EquitySnapshot.mode == mode, EquitySnapshot.paper_id.is_(None)
            )
        )
        first_today = await session.scalar(
            select(EquitySnapshot.equity_usd)
            .where(
                EquitySnapshot.mode == mode,
                EquitySnapshot.paper_id.is_(None),
                EquitySnapshot.recorded_at >= day_start,
            )
            .order_by(EquitySnapshot.recorded_at)
            .limit(1)
        )
    return peak, first_today


async def _asset_taken(paper: Paper) -> int | None:
    """Another paper with an open position on the asset in this mode, or an
    entry approved and waiting to fill - an exchange account holds one net
    position per coin, so demo follows the same rule as live."""
    async with async_session() as session:
        holder = await session.scalar(
            select(Position.paper_id).where(
                Position.asset == paper.asset,
                Position.mode == paper.mode,
                Position.closed_at.is_(None),
                Position.paper_id != paper.id,
            )
        )
        if holder is None:
            holder = await session.scalar(
                select(TradingDecision.paper_id)
                .join(Paper, Paper.id == TradingDecision.paper_id)
                .where(
                    Paper.asset == paper.asset,
                    TradingDecision.mode == paper.mode,
                    TradingDecision.signal == "enter",
                    TradingDecision.outcome == "approved",
                    TradingDecision.paper_id != paper.id,
                )
            )
    return holder


async def _require_cash(paper: Paper, margin: Decimal, notional: Decimal) -> Decimal:
    """The free balance left after the order's margin and fee; Rejected without it."""
    cash = await free_cash(paper.mode) or Decimal(0)
    needed = margin + notional * await taker_fee_rate()
    if cash < needed:
        raise Rejected(f"insufficient free balance: need {needed:.2f}, have {cash:.2f}")
    return cash - needed


async def _size_entry(decision: TradingDecision, paper: Paper) -> tuple[Decimal, str | None]:
    """Returns (approved notional, note) or raises Rejected. An averaging
    paper (docs/papers.md#averaging-papers) is held to its own limits - its
    max margin and max drawdown - not the account's drawdown / daily loss,
    the position limits or its loss-limit block: its first entry is its
    fixed size, if the cash is there."""
    if not paper.enabled:
        raise Rejected("paper is disabled")
    if await is_kill_switch_active():
        raise Rejected("watchdog kill switch active")
    averaging = paper.kind == "averaging"
    if not averaging and await is_entry_blocked(paper.executor, paper.id):
        raise Rejected("entries blocked by the risk engine")
    if holder := await _asset_taken(paper):
        raise Rejected(f"{paper.asset} is already held in {paper.mode} by paper {holder}")
    if averaging:
        assert paper.initial_size_usd is not None  # required on an averaging paper
        margin = paper.initial_size_usd
        await _require_cash(paper, margin, margin * paper.leverage)
        return margin * paper.leverage, None
    budget = await paper_budget(paper.mode)
    total = await mode_total(paper.mode)
    equity = await mode_equity(paper.mode)
    if budget is None or total is None or equity is None:
        raise Rejected(f"no {paper.mode} balance data")
    if budget <= 0:
        raise Rejected("no budget")

    # A fixed first entry (docs/papers.md#averaging-papers), else the budget share.
    margin = paper.initial_size_usd if paper.initial_size_usd is not None else budget
    notional = margin * paper.leverage
    async with async_session() as session:
        open_positions = (
            await session.scalars(
                select(Position).where(Position.mode == paper.mode, Position.closed_at.is_(None))
            )
        ).all()
    peak, day_start_equity = await _peak_and_day_start(paper.mode)
    result = evaluate(
        ProposedOrder(
            strategy_id=str(paper.id),
            asset=paper.asset,
            notional_usd=float(notional),
            direction=decision.direction,
            leverage=float(paper.leverage),
        ),
        [
            RiskPosition(
                strategy_id=str(p.paper_id),
                asset=p.asset,
                notional_usd=float(p.size * p.entry_price),
                direction=p.direction,
                leverage=float(p.leverage),
            )
            for p in open_positions
        ],
        daily_pnl_usd=float(
            equity - (day_start_equity if day_start_equity is not None else equity)
        ),
        current_equity_usd=float(equity),
        peak_equity_usd=float(peak if peak is not None else equity),
        capital_usd=float(total),
    )
    if not result.approved:
        raise Rejected(result.reason or "rejected by limits")
    approved = Decimal(str(result.approved_notional_usd))
    await _require_cash(paper, approved / paper.leverage, approved)
    return approved, result.reason


def _low_margin_warning(
    paper: Paper,
    margin: Decimal,
    locked: Decimal | None,
    cap: Decimal | None,
    cash_left: Decimal,
) -> str | None:
    """The owner's warning once this add leaves room - under the max margin
    and in the free balance - for one more dip add or none: once only, at the
    add that gets there (docs/papers.md#averaging-papers)."""
    dip = add_terms(paper, AVERAGE_DOWN)
    if dip is None or dip[0] <= 0:
        return None
    step = dip[0]
    cap_left = None if cap is None or locked is None else cap - locked - margin
    left = cash_left if cap_left is None else min(cap_left, cash_left)
    if left // step > 1 or (left + margin) // step <= 1:
        return None
    adds = "1 more add" if left // step == 1 else "no more adds"
    by = "the free balance" if cap_left is None or cash_left < cap_left else "its max margin"
    margins = (
        "" if cap is None or locked is None else f"margin ${locked + margin:.2f} of ${cap:.2f}, "
    )
    return (
        f"paper {paper.id} {paper.asset} ({paper.mode}): {adds} left before {by} - "
        f"{margins}free balance ${cash_left:.2f}. Add cash and raise the paper's max "
        "margin, or a deeper drop runs to the give-up or a margin call."
    )


async def _size_add(paper: Paper, reason: str) -> tuple[Decimal, str | None]:
    """An add's notional (docs/papers.md#averaging-papers): a dip add at the
    paper's add size and add leverage, a signal add like the first entry
    (add_terms) - not resized by the limits, a dip add keeps the position
    from a margin call - and the low-margin warning it calls for, if any.
    Rejected beyond the paper's max margin or without free cash for its
    margin and fee - not by a risk block: the open position must be able to
    defend itself."""
    if not paper.enabled:
        raise Rejected("paper is disabled")
    if await is_kill_switch_active():
        raise Rejected("watchdog kill switch active")
    terms = add_terms(paper, reason)
    if paper.kind != "averaging" or terms is None:
        raise Rejected("averaging down is off for this paper")
    margin, leverage = terms
    notional = margin * leverage
    locked: Decimal | None = None
    cap: Decimal | None = None
    if paper.max_margin_usd is not None:
        async with async_session() as session:
            locked = await session.scalar(
                select(Position.margin_usd).where(
                    Position.paper_id == paper.id,
                    Position.mode == paper.mode,
                    Position.closed_at.is_(None),
                )
            )
            cap = paper.max_margin_usd
            if paper.compound_margin:
                # Compounding: the max margin grows with the closed positions'
                # realized PnL in this mode (losses shrink it).
                realized = await session.scalar(
                    select(func.coalesce(func.sum(Position.realized_pnl_usd), 0)).where(
                        Position.paper_id == paper.id,
                        Position.mode == paper.mode,
                        Position.closed_at.is_not(None),
                    )
                )
                cap += realized or Decimal(0)
        if locked is not None and locked + margin > cap:
            raise Rejected(f"max margin reached: {locked:.2f} locked + {margin:.2f} > {cap:.2f}")
    cash_left = await _require_cash(paper, margin, notional)
    return notional, _low_margin_warning(paper, margin, locked, cap, cash_left)


async def _decide_pending() -> None:
    async with async_session() as session:
        ids = (
            await session.scalars(
                select(TradingDecision.id)
                .where(TradingDecision.outcome == "pending")
                .order_by(TradingDecision.decided_at, TradingDecision.id)
            )
        ).all()
    for decision_id in ids:
        try:
            await _decide(decision_id)
        except Exception:
            logger.exception("decision %d: risk check failed - left pending", decision_id)


async def _first_rejected_add(session: AsyncSession, decision: TradingDecision) -> bool:
    """No add of the paper's open position was rejected before this one - the
    owner is told once per position, not on every per-candle retry."""
    opened_at = await session.scalar(
        select(Position.opened_at).where(
            Position.paper_id == decision.paper_id,
            Position.mode == decision.mode,
            Position.closed_at.is_(None),
        )
    )
    if opened_at is None:
        return False
    earlier = await session.scalar(
        select(TradingDecision.id)
        .where(
            TradingDecision.paper_id == decision.paper_id,
            TradingDecision.mode == decision.mode,
            TradingDecision.signal == "add",
            TradingDecision.outcome == "rejected_by_risk",
            TradingDecision.decided_at >= opened_at,
            TradingDecision.id != decision.id,
        )
        .limit(1)
    )
    return earlier is None


async def _decide(decision_id: int) -> None:
    warning: str | None = None  # a rejected add, alerted once committed
    async with async_session() as session, session.begin():
        decision = await session.scalar(
            select(TradingDecision)
            .where(TradingDecision.id == decision_id, TradingDecision.outcome == "pending")
            .with_for_update(skip_locked=True)
        )
        if decision is None:
            return
        if decision.signal == "exit":
            decision.risk_approved = True
            decision.risk_reason = "exit - never blocked"
            decision.outcome = "approved"
            return
        paper = await session.get(Paper, decision.paper_id)
        try:
            if paper is None:
                raise Rejected("paper not found")
            if decision.signal == "add":
                notional, warning = await _size_add(paper, decision.reason)
                note = None
            else:
                notional, note = await _size_entry(decision, paper)
        except Rejected as exc:
            decision.risk_approved = False
            decision.risk_reason = str(exc)
            decision.outcome = "rejected_by_risk"
            session.add(
                RiskEvent(
                    occurred_at=datetime.now(UTC),
                    paper_id=decision.paper_id,
                    type="entry_rejected",
                    detail=str(exc),
                )
            )
            if decision.signal == "add" and await _first_rejected_add(session, decision):
                warning = (
                    f"paper {decision.paper_id} {decision.asset} ({decision.mode}): add rejected - "
                    f"{exc}. Averaging is paused until there's free balance (retried every "
                    "candle); a deeper drop can liquidate the position - top up the account."
                )
        else:
            decision.risk_approved = True
            decision.risk_reason = note or "approved"
            decision.position_size_usd = notional
            decision.outcome = "approved"
    if warning is not None:
        await alert("risk-engine", "warning", warning)


async def _record_equity(last_recorded: float) -> float:
    if time.time() - last_recorded < EQUITY_SNAPSHOT_SECONDS:
        return last_recorded
    for mode in ("demo", "live"):
        equity = await mode_equity(mode)
        if equity is None:
            continue
        async with async_session() as session:
            session.add(EquitySnapshot(mode=mode, equity_usd=equity, recorded_at=datetime.now(UTC)))
            await session.commit()
    return time.time()


def loss_limit(backtest_returns_pct: list[float], leverage: float) -> tuple[Decimal, str]:
    """The paper's loss limit (share of its budget) and where it comes from:
    PAPER_LOSS_DISABLE_PCT, or its backtest's max drawdown (compounded at its
    leverage) x PAPER_LOSS_BACKTEST_MULTIPLE when that's more - a strategy
    whose normal losing streaks run deeper isn't stopped inside them. At most
    the whole budget."""
    default = Decimal(str(settings.paper_loss_disable_pct))
    if not backtest_returns_pct:
        return default, "default"
    drawdown = Decimal(str(-max_drawdown(backtest_returns_pct, leverage)))
    scaled = min(drawdown * Decimal(str(settings.paper_loss_backtest_multiple)), Decimal(1))
    if scaled <= default:
        return default, "default"
    multiple = settings.paper_loss_backtest_multiple
    return scaled, f"backtest max drawdown {drawdown:.1%} x {multiple}"


async def _backtest_returns(paper_id: int) -> list[float]:
    async with async_session() as session:
        rows = await session.scalars(
            select(BacktestTrade.return_pct)
            # An averaging paper's position still open isn't realized.
            .where(BacktestTrade.paper_id == paper_id, BacktestTrade.exit_reason != OPEN_AT_END)
            .order_by(BacktestTrade.closed_at, BacktestTrade.id)
        )
        return [float(r) for r in rows.all()]


async def _disable_losing_papers() -> None:
    """Realized loss since the paper was (re-)enabled >= its loss_limit() of
    its budget: block new entries at once, disable once the paper is flat."""
    async with async_session() as session:
        papers = (
            await session.scalars(
                # An averaging paper's own max margin / max drawdown are its loss limits.
                select(Paper).where(Paper.enabled.is_(True), Paper.kind.not_in(AVERAGING_KINDS))
            )
        ).all()
    for paper in papers:
        budget = await paper_budget(paper.mode)
        if not budget:
            continue
        loss_pct, basis = loss_limit(await _backtest_returns(paper.id), float(paper.leverage))
        async with async_session() as session, session.begin():
            realized = await session.scalar(
                select(func.coalesce(func.sum(Position.realized_pnl_usd), 0)).where(
                    Position.paper_id == paper.id,
                    Position.mode == paper.mode,
                    Position.closed_at >= paper.enabled_at,
                )
            )
            if Decimal(realized or 0) > -loss_pct * budget:
                continue
            reason = (
                f"realized loss since enabled {Decimal(realized or 0):.2f} reached {loss_pct:.1%} "
                f"of budget {budget:.2f} (limit: {basis})"
            )
            busy = await session.scalar(
                select(func.count(Position.id)).where(
                    Position.paper_id == paper.id, Position.closed_at.is_(None)
                )
            ) or await session.scalar(
                select(func.count(TradingDecision.id)).where(
                    TradingDecision.paper_id == paper.id,
                    TradingDecision.outcome.in_(IN_FLIGHT_OUTCOMES),
                )
            )
            if busy:
                await block_paper(paper.id, reason)
                continue
            locked = await session.get(Paper, paper.id, with_for_update=True)
            if locked is None or not locked.enabled:
                continue
            locked.enabled = False
            locked.disabled_by = "risk_engine"
            locked.disabled_reason = reason
            locked.updated_at = datetime.now(UTC)
            session.add(
                RiskEvent(
                    occurred_at=datetime.now(UTC),
                    paper_id=paper.id,
                    type="paper_disabled",
                    detail=reason,
                )
            )
        await unblock_paper(paper.id)
        await alert("risk-engine", "warning", f"paper {paper.id} disabled: {reason}")


async def _liquidation_fallback(adapter: MarketAdapter) -> None:
    age = await heartbeat_age_seconds(EXECUTION_ENGINE)
    if age is None or age > settings.execution_heartbeat_stale_seconds:
        await liquidate_breached(adapter, "risk-engine")


class RiskEngine:
    def __init__(self, adapter: MarketAdapter) -> None:
        self._adapter = adapter
        self._last_equity_snapshot = 0.0

    async def run_once(self) -> None:
        for step in (
            _decide_pending,
            self._record_equity,
            _disable_losing_papers,
            self._liquidation_fallback,
        ):
            try:
                await step()
            except Exception:
                logger.exception("risk engine step %s failed", step.__name__)

    async def _record_equity(self) -> None:
        self._last_equity_snapshot = await _record_equity(self._last_equity_snapshot)

    async def _liquidation_fallback(self) -> None:
        await _liquidation_fallback(self._adapter)
