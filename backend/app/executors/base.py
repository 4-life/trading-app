"""Shared strategy-executor loop (docs/strategy-executor.md).

Every EXECUTOR_POLL_SECONDS, for each enabled paper of this executor: skip it
while it has an order in flight, otherwise ask the strategy for a signal and
queue it as a `pending` trading decision (the order queue - see
app/execution_engine/models.py's TradingDecision). The risk engine and the
execution engine take it from there. Executors never size or place orders.
"""

import logging
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Protocol

from sqlalchemy import func, select

from app.config import settings
from app.db import async_session
from app.execution_engine.demo import open_side
from app.execution_engine.models import IN_FLIGHT_OUTCOMES, Order, Position, TradingDecision
from app.executors.paper_exits import paper_exit, with_paper_levels
from app.executors.position_management import (
    REOPEN_IN_TREND,
    SIGNAL_ADD,
    TAKE_PROFIT_EXIT,
    Lot,
    held_lots,
    managed_signal,
    next_unwind,
    signal_add,
    take_profit_close,
    take_profit_sell,
    unwind_buffer,
)
from app.feature_engine.models import Feature
from app.market_data.limits import market_limits
from app.market_data.models import Candle, Trade
from app.order_queue import Direction, Signal, queue_decision
from app.papers.models import TRADING_KINDS, Paper
from app.risk_engine.blocks import is_entry_blocked
from app.scheduling import sleep_until_next
from app.system.auto_open import is_auto_open_enabled
from app.system.exchange_api import taker_fee_rate
from app.watchdog.redis_client import is_kill_switch_active, set_heartbeat

logger = logging.getLogger(__name__)


# A trade older than this isn't the current price - fall back to the candle close.
LIVE_PRICE_MAX_AGE = timedelta(seconds=60)

# A reopening paper's trend, checked once per closed candle: paper id ->
# (that candle's open time, the strategy's own trade still open at its close).
_trend_checked: dict[int, tuple[datetime, bool]] = {}


@dataclass(frozen=True)
class Tick:
    """What a strategy sees for one paper on one poll."""

    paper: Paper
    position: Position | None
    price: Decimal
    poll_started_at: datetime


class Strategy(Protocol):
    name: str

    async def before_poll(self, papers: list[Paper], poll_started_at: datetime) -> None:
        """Runs once per poll with every enabled paper of this executor, even
        the ones skipped below - for state that must advance every poll."""

    async def decide(self, tick: Tick) -> Signal | None: ...


def direction_allowed(paper_direction: str, direction: Direction) -> bool:
    return paper_direction in ("both", direction)


async def recent_candles(asset: str, timeframe: str, limit: int) -> list[Candle]:
    """The latest `limit` closed candles, ascending by open_time. The newest
    stored candle is the forming one and is left out - signals use closed
    candles only (same rule as the feature engine)."""
    async with async_session() as session:
        rows = await session.scalars(
            select(Candle)
            .where(Candle.asset == asset, Candle.interval == timeframe)
            .order_by(Candle.open_time.desc())
            .limit(limit + 1)
        )
        return list(reversed(rows.all()[1:]))


async def latest_price(asset: str, timeframe: str) -> Decimal | None:
    """Close of the latest closed candle."""
    candles = await recent_candles(asset, timeframe, 1)
    return candles[-1].close if candles else None


async def live_trade_price(asset: str) -> Decimal | None:
    """Latest trade (WebSocket) - stops and take-profits are checked between
    candle closes. None if no trade arrived within LIVE_PRICE_MAX_AGE."""
    async with async_session() as session:
        row = (
            await session.execute(
                select(Trade.price, Trade.exchange_timestamp)
                .where(Trade.asset == asset)
                .order_by(Trade.exchange_timestamp.desc())
                .limit(1)
            )
        ).first()
    if row is None or datetime.now(UTC) - row.exchange_timestamp > LIVE_PRICE_MAX_AGE:
        return None
    return Decimal(row.price)


async def latest_feature_sets(
    asset: str, timeframe: str, names: tuple[str, ...], count: int
) -> list[tuple[datetime, dict[str, float]]]:
    """The latest `count` feature readings (newest first) that contain every
    name in `names`, as (computed_at, values). Feature-engine writes one
    reading per closed candle under one `computed_at`."""
    async with async_session() as session:
        rows = (
            await session.execute(
                select(Feature.name, Feature.value, Feature.computed_at)
                .where(
                    Feature.asset == asset,
                    Feature.interval == timeframe,
                    Feature.name.in_(names),
                )
                .order_by(Feature.computed_at.desc())
                .limit(len(names) * (count + 10))
            )
        ).all()
    by_time: dict[datetime, dict[str, float]] = {}
    for name, value, computed_at in rows:
        by_time.setdefault(computed_at, {})[name] = float(value)
    complete = [
        (t, by_time[t]) for t in sorted(by_time, reverse=True) if len(by_time[t]) == len(names)
    ]
    return complete[:count]


async def last_placed_decision(paper: Paper) -> TradingDecision | None:
    """The paper's latest executed decision in its current mode."""
    async with async_session() as session:
        decision: TradingDecision | None = await session.scalar(
            select(TradingDecision)
            .where(
                TradingDecision.paper_id == paper.id,
                TradingDecision.mode == paper.mode,
                TradingDecision.outcome == "placed",
            )
            .order_by(TradingDecision.decided_at.desc())
            .limit(1)
        )
    return decision


async def last_entry_at(paper: Paper, direction: Direction) -> datetime | None:
    """When the paper's latest entry in `direction` (in its mode) was placed."""
    async with async_session() as session:
        at: datetime | None = await session.scalar(
            select(TradingDecision.decided_at)
            .where(
                TradingDecision.paper_id == paper.id,
                TradingDecision.mode == paper.mode,
                TradingDecision.signal == "enter",
                TradingDecision.direction == direction,
                TradingDecision.outcome == "placed",
            )
            .order_by(TradingDecision.decided_at.desc())
            .limit(1)
        )
    return at


async def _papers(executor: str) -> list[Paper]:
    async with async_session() as session:
        rows = await session.scalars(
            select(Paper)
            # Scanner papers don't trade - their single children do.
            .where(
                Paper.executor == executor,
                Paper.enabled.is_(True),
                Paper.kind.in_(TRADING_KINDS),
                Paper.prep_status.is_(None),  # not until it's backfilled / backtested
            )
            .order_by(Paper.id)
        )
        return list(rows.all())


async def _has_in_flight(paper_id: int) -> bool:
    async with async_session() as session:
        found = await session.scalar(
            select(TradingDecision.id)
            .where(
                TradingDecision.paper_id == paper_id,
                TradingDecision.outcome.in_(IN_FLIGHT_OUTCOMES),
            )
            .limit(1)
        )
    return found is not None


async def _open_position(paper_id: int) -> Position | None:
    async with async_session() as session:
        position: Position | None = await session.scalar(
            select(Position).where(Position.paper_id == paper_id, Position.closed_at.is_(None))
        )
    return position


async def _already_queued(paper: Paper, signal: Signal) -> bool:
    """The same signal was already queued since the latest reading (closed
    candle) - e.g. an entry the risk engine rejected. Each signal is queued
    at most once per candle; an exit and the reversed entry are different
    signals, and so are exits with different reasons (a partial close, then
    a stop-loss), so they all still go through on the same candle."""
    async with async_session() as session:
        reading_at = await session.scalar(
            select(func.max(Feature.computed_at)).where(
                Feature.asset == paper.asset, Feature.interval == paper.timeframe
            )
        )
        if reading_at is None:
            return False
        found = await session.scalar(
            select(TradingDecision.id)
            .where(
                TradingDecision.paper_id == paper.id,
                TradingDecision.mode == paper.mode,
                TradingDecision.signal == signal.signal,
                TradingDecision.direction == signal.direction,
                TradingDecision.reason == signal.reason,
                TradingDecision.decided_at >= reading_at,
            )
            .limit(1)
        )
    return found is not None


async def _buys(position: Position) -> list[tuple[datetime, Decimal, Decimal]]:
    """The position's filled opening orders (its first entry and every add),
    oldest first, as (time, fill price, size)."""
    async with async_session() as session:
        rows = await session.execute(
            select(Order.created_at, Order.fill_price, Order.size)
            .where(
                Order.position_id == position.id,
                Order.side == open_side(position.direction),
                Order.fill_price.is_not(None),
            )
            .order_by(Order.created_at, Order.id)
        )
        return [(at, Decimal(price), Decimal(size)) for at, price, size in rows.all()]


async def _lots(position: Position, first_buy: Decimal) -> list[Lot]:
    """The position's dip units still held, from its filled orders after the
    first buy - buys and partial closes (unwinds), oldest first."""
    async with async_session() as session:
        rows = await session.execute(
            select(Order.side, Order.fill_price, Order.size)
            .where(Order.position_id == position.id, Order.fill_price.is_not(None))
            .order_by(Order.created_at, Order.id)
        )
    opening = open_side(position.direction)
    fills = [
        ("buy" if side == opening else "sell", Decimal(price), Decimal(size))
        for side, price, size in rows.all()
    ][1:]  # after the first buy
    direction: Direction = "long" if position.direction == "long" else "short"
    return held_lots(direction, first_buy, fills)


async def _averaging(
    strategy: Strategy, tick: Tick, position: Position
) -> tuple[Signal | None, datetime | None]:
    """An averaging paper's open position (docs/papers.md#averaging-papers) at
    the latest trade price: its give-up or next add, else selling its lowest
    dip unit but the lowest (kept to the close) at the level of the add
    above it, else its take-profit - an
    intraday paper's at once, otherwise the strategy's sell once the gain
    has reached it (the strategy's other exits are off - it holds through
    the dips), else a signal add - the strategy's
    entry signal; and when its last buy filled."""
    buys = await _buys(position)
    if not buys:
        return None, None
    paper = tick.paper
    price = await live_trade_price(paper.asset) or tick.price
    direction: Direction = "long" if position.direction == "long" else "short"
    # The exchange's maintenance margin: an early liquidation moves the levels up.
    limits = await market_limits(paper.asset)
    signal = managed_signal(
        direction,
        price,
        position.entry_price,
        position.size,
        position.margin_usd,
        buys[0][1],
        paper.max_drawdown_pct,
        None if limits is None else limits.maintenance_margin,
    )
    if signal is None:
        lots = await _lots(position, buys[0][1])
        buffer = unwind_buffer(await taker_fee_rate())
        signal = next_unwind(direction, price, buys[0][1], lots, position.size, buffer)
    realized = position.realized_pnl_usd or Decimal(0)
    if signal is None and paper.intraday:
        signal = take_profit_close(
            direction,
            price,
            position.entry_price,
            position.size,
            position.margin_usd,
            realized,
            paper.take_profit_pct,
        )
    elif signal is None:
        sell = await strategy.decide(tick)
        if sell is not None:
            signal = take_profit_sell(
                sell,
                price,
                position.entry_price,
                position.size,
                position.margin_usd,
                realized,
                paper.take_profit_pct,
            )
    if signal is None:
        # The strategy's entry rule, as if flat - its signal adds a unit.
        entry = await strategy.decide(replace(tick, position=None))
        signal = signal_add(entry, direction)
    return signal, buys[-1][0]


def add_window(
    reason: str, last_buy_at: datetime | None, reading_at: datetime | None
) -> datetime | None:
    """Since when an earlier add of the same kind holds back this one. A dip
    add: since the position's last buy and the latest reading (closed candle)
    - a filled one lifts the margin left, so the next comes only when the loss
    catches up again; a rejected one (e.g. no free cash) is retried once per
    candle, not every pass. A signal add: since the latest reading only - its
    entry signal holds for the whole candle, so a filled one doesn't stop the
    next pass from adding again (at most one per candle)."""
    if reason == SIGNAL_ADD:
        return reading_at or last_buy_at
    return max((t for t in (last_buy_at, reading_at) if t is not None), default=None)


async def _add_queued(paper: Paper, signal: Signal, last_buy_at: datetime | None) -> bool:
    """An add of the same kind was already queued in its add_window. A signal
    add counts the position's entry too: no add on the candle it opened on."""
    async with async_session() as session:
        reading_at = await session.scalar(
            select(func.max(Feature.computed_at)).where(
                Feature.asset == paper.asset, Feature.interval == paper.timeframe
            )
        )
        since = add_window(signal.reason, last_buy_at, reading_at)
        same_kind = (TradingDecision.signal == "add") & (TradingDecision.reason == signal.reason)
        if signal.reason == SIGNAL_ADD:
            same_kind = same_kind | (TradingDecision.signal == "enter")
        found = await session.scalar(
            select(TradingDecision.id)
            .where(
                TradingDecision.paper_id == paper.id,
                TradingDecision.mode == paper.mode,
                same_kind,
                *([TradingDecision.decided_at >= since] if since is not None else []),
            )
            .limit(1)
        )
    return found is not None


def reopens(paper: Paper) -> bool:
    """An intraday averaging paper reopening after a take-profit while the trend lasts."""
    return paper.kind == "averaging" and paper.intraday and paper.reopen_in_trend


async def _in_trend(paper: Paper, candle: datetime) -> bool:
    """The strategy's own long trade still open at the close of `candle` (the
    latest closed one) - the paper's backtest replayed over its stored
    candles, as the averaging backtest decides it (app/backtest/averaging.py
    in_trend). Once per candle: the replay is heavy."""
    checked = _trend_checked.get(paper.id)
    if checked is not None and checked[0] == candle:
        return checked[1]
    # Lazy: the backtests import this module.
    from app.backtest.averaging import STRATEGY_TRADES, in_trend
    from app.backtest.bars import load_bars

    trades_of = STRATEGY_TRADES.get(paper.executor)
    bars = await load_bars(paper)
    held = (
        trades_of is not None
        and bool(bars)
        and bars[-1].time == candle
        and candle in in_trend(bars, trades_of(paper, bars, None))
    )
    _trend_checked[paper.id] = (candle, held)
    return held


async def _reopen_in_trend(paper: Paper) -> Signal | None:
    """A flat reopening paper (reopens): its last position closed at its
    intraday take-profit during the latest closed candle and the strategy's
    trend lasts at that candle's close - a fresh long there; else None. Not
    caught up later: the candle after missed (or rejected), no reopen."""
    async with async_session() as session:
        opens = (
            await session.scalars(
                select(Candle.open_time)
                .where(Candle.asset == paper.asset, Candle.interval == paper.timeframe)
                .order_by(Candle.open_time.desc())
                .limit(2)
            )
        ).all()
        last: Position | None = await session.scalar(
            select(Position)
            .where(
                Position.paper_id == paper.id,
                Position.mode == paper.mode,
                Position.closed_at.is_not(None),
            )
            .order_by(Position.closed_at.desc())
            .limit(1)
        )
    if len(opens) < 2 or last is None or last.closed_at is None:
        return None
    forming, candle = opens
    if last.direction != "long" or last.exit_reason != TAKE_PROFIT_EXIT:
        return None
    if not candle <= last.closed_at < forming or not await _in_trend(paper, candle):
        return None
    return Signal("enter", "long", REOPEN_IN_TREND)


async def _entry_allowed(executor: str, paper: Paper, direction: Direction) -> bool:
    """Entries only - exits are never blocked (docs/strategy-executor.md)."""
    if not direction_allowed(paper.direction, direction):
        return False
    if await is_kill_switch_active():
        return False
    # An averaging paper isn't held back by risk blocks (docs/papers.md#averaging-papers).
    return paper.kind == "averaging" or not await is_entry_blocked(executor, paper.id)


async def run_once(strategy: Strategy) -> None:
    poll_started_at = datetime.now(UTC)
    # Watchdog's position-protection check reads this.
    await set_heartbeat(strategy.name)
    papers = await _papers(strategy.name)
    await strategy.before_poll(papers, poll_started_at)
    live_auto = await is_auto_open_enabled()

    for paper in papers:
        try:
            # Switch off: no entries and no exits for live papers.
            if paper.mode == "live" and not live_auto:
                continue
            if await _has_in_flight(paper.id):
                continue
            price = await latest_price(paper.asset, paper.timeframe)
            if price is None:
                logger.info("paper %d: no %s candles yet - skipping", paper.id, paper.timeframe)
                continue
            tick = Tick(
                paper=paper,
                position=await _open_position(paper.id),
                price=price,
                poll_started_at=poll_started_at,
            )
            last_buy_at: datetime | None = None
            if tick.position is not None and paper.kind == "averaging":
                signal, last_buy_at = await _averaging(strategy, tick, tick.position)
            else:
                signal = await _paper_exit(tick) or await strategy.decide(tick)
                if signal is None and tick.position is None and reopens(paper):
                    signal = await _reopen_in_trend(paper)
                if signal is not None and signal.signal == "enter":
                    signal = with_paper_levels(paper, signal, tick.price)
            if signal is None:
                continue
            if signal.signal == "add":
                if await _add_queued(paper, signal, last_buy_at):
                    continue
            elif await _already_queued(paper, signal):
                continue
            if signal.signal != "exit" and not await _entry_allowed(
                strategy.name, paper, signal.direction
            ):
                continue
            await queue_decision(paper, signal, tick.price)
        except Exception:
            # One broken paper must not stop the others.
            logger.exception("%s: paper %d failed", strategy.name, paper.id)


async def _paper_exit(tick: Tick) -> Signal | None:
    """The paper's own stop-loss or take-profit reached by the open position,
    against the latest trade price (paper_exits.py) - before the strategy."""
    position = tick.position
    if position is None:
        return None
    if tick.paper.stop_loss_pct is None and tick.paper.price_take_profit_pct is None:
        return None
    direction: Direction = "long" if position.direction == "long" else "short"
    price = await live_trade_price(tick.paper.asset) or tick.price
    return paper_exit(tick.paper, direction, position.entry_price, price)


async def run(strategy: Strategy) -> None:
    while True:
        await run_once(strategy)
        # 1 s after the feature engine's 5 s grid, so a new reading is seen at once.
        await sleep_until_next(settings.executor_poll_seconds, offset_seconds=1)
