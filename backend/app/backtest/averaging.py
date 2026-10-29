"""Temporary averaging-paper backtest (docs/papers.md#averaging-papers): the
paper's executor gives the entries and the sell signals - the long entries
and exits of its own backtest, replayed without saving, plus every candle
it signals a long on while its own trade is open (as live asks it on every
candle) - and the paper's
averaging rules manage each position candle by candle. Replaces the
paper's rows in `backtest_trades`, one per position. Run after a backfill:

    python -m app.backtest.averaging [YYYY-MM-DD]

Trades start on the given date - else the paper's `backtest_start`, else the
whole history.

Flat, a candle the strategy entered a long on opens a position at that
entry's price: `initial_size_usd` margin at the paper's leverage. Inside
each later candle the price is taken down to its low first (worst case):
every add level (where the margin left falls to ADD_AT_MARGIN_LEFT), the
give-up and the liquidation price it reaches fire in price order - an add
(`add_size_usd` margin at `add_leverage`) fills at its level, the give-up
and liquidation close the position there - at the open if the candle
gapped past them. A position still open then closes at a sell signal of the
strategy on the candle (its exit's price) if the position's whole PnL
there - its unwinds' realized PnL plus the size held - is at least
`take_profit_pct` of the margin backing it - the take-profit is a
floor, not an exit of its own; a sell below it is ignored. Still open, a
strategy entry signal on the candle adds a unit at that entry's price (a
signal add, sized like the first entry). On the candle's way up each
unit of the grid - every buy: the first, every dip add and signal add -
lowest first, but never the lowest held, kept to the close, is sold at
the next-higher unit's price (unwind_level, as live) - not in a candle
that added units, whose high may have come before its low.
After a take-profit close the live paper stops until the owner enables it
again; here the next entry signal opens the next position, as if
re-enabled. An `intraday` paper closes at its take-profit at once - when
the candle's high reaches the price where the position's whole PnL makes
it, not in a candle that added units - and keeps running.
With `max_margin_usd` the adds stop at the budget: the cash, starting
there with every closed position's PnL added to it, but never more than
`max_margin_usd` - profits are banked, losses shrink it; under
`initial_size_usd` no position opens. With `compound_margin` the budget is
all the cash - profits compound.

Each row: `entry_price` the average entry, `stop_loss_price` the give-up
level, `entry_reason` the strategy's reason + the number of adds,
`margin_usd` / `pnl_usd` its peak margin (the most locked at once - the cash
it needed) and the PnL net of fees, and `return_pct` = PnL / that margin /
the paper's leverage - so the risk
engine, which multiplies by the leverage, reads % of margin. Its buys (the
first entry and every add) go to `backtest_fills`, for the chart.
Fees: the selected provider's maker fee on every fill. Slippage: every fill
FILL_SLIPPAGE against the position - a buy higher, a sell lower - so a run
that only survives on the exact levels doesn't.

A short paper (`direction` short) is the same, mirrored: the strategy's short
entries open it and its short exits are the sell signals, each candle takes
the price up to its high first (the adds, the give-up and the liquidation
above the entry), then down (the unwinds and the take-profit); its "buys"
are the sells that open or add to it - the fills' sides stay "buy" (adds)
and "sell" (reductions). With `direction` both, each position takes the
direction of the entry that opens it - a long or a short, one at a time;
the other direction's signals are ignored while it's open."""

import logging
import sys
from bisect import bisect_left
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import delete, select

from app.backtest import keltner, regime, supertrend, vwap
from app.backtest.bars import STOP_SLIPPAGE, Bar, Fill, SimTrade, load_bars
from app.backtest.models import OPEN_AT_END, BacktestFill, BacktestTrade
from app.config import settings
from app.db import async_session
from app.executors.position_management import (
    MAX_DRAWDOWN_EXIT,
    OUT_OF_MARGIN_EXIT,
    REOPEN_IN_TREND,
    TAKE_PROFIT_EXIT,
    margin_levels,
    unwind_buffer,
    unwind_level,
    unwound_unit,
)
from app.market_data.limits import Limits, market_limits
from app.notifications.error_reporting import run_service
from app.papers.models import Paper
from app.system.exchange_api import maker_fee_rate

logger = logging.getLogger(__name__)

LIQUIDATION_EXIT = "liquidation"  # the execution engine's maintenance-margin close
# A paper's every fill (entries, adds, unwinds, closes) this much against it:
# the backtest's exact levels don't happen live.
FILL_SLIPPAGE = STOP_SLIPPAGE

# The executors whose backtest gives an averaging paper its entries and sells.
STRATEGY_TRADES: dict[str, Callable[[Paper, list[Bar], datetime | None], list[SimTrade]]] = {
    "vwap": vwap.simulate_paper,
    "supertrend": supertrend.simulate_paper,
    "keltner": keltner.simulate_paper,
    "regime": regime.simulate_paper,
}
# Every candle a strategy signals a long on, its own trade held or not - the
# entries its trades miss.
ENTRY_SIGNALS: dict[str, Callable[[Paper, list[Bar]], list[SimTrade]]] = {
    "vwap": vwap.entry_signals,
    "supertrend": supertrend.entry_signals,
    "keltner": keltner.entry_signals,
    "regime": regime.entry_signals,
}


@dataclass(frozen=True)
class Rules:
    """An averaging paper's parameters (shares as fractions)."""

    leverage: float
    initial_size: float
    add_leverage: float
    add_size: float
    take_profit: float
    max_drawdown: float | None  # None: the automatic give-up only (OUT_OF_MARGIN_EXIT)
    maintenance: float  # the execution engine's maintenance share of the margin
    # The starting cash and the most margin a position may lock at once.
    max_margin: float | None = None
    # The cash's profits are re-risked: a position's budget is all the cash,
    # over max_margin too (otherwise at most max_margin).
    compound: bool = False
    intraday: bool = False  # close at the take-profit at once, no strategy sell
    # Intraday: after a take-profit, a fresh position at that candle's close
    # while the strategy's own trade is still open there (in_trend).
    reopen: bool = False
    # The exchange's maintenance margin, a share of the notional
    # (app/market_data/limits.py): liquidated under it instead of `maintenance`.
    maintenance_notional: float | None = None
    # long / short / both: the positions it opens - a short's mirrored (the module's doc).
    direction: str = "long"
    # Every fill this much (a share of the price) against the position - a buy
    # higher, a sell lower (a short: mirrored); FILL_SLIPPAGE for a paper.
    slippage: float = 0.0

    @property
    def directions(self) -> tuple[str, ...]:
        return ("long", "short") if self.direction == "both" else (self.direction,)


def _sign(direction: str) -> int:
    return -1 if direction == "short" else 1


def _worse(sign: int, a: float, b: float) -> float:
    """The price further against the position: a long's lower, a short's higher."""
    return min(a, b, key=lambda x: sign * x)


def _better(sign: int, a: float, b: float) -> float:
    """The price further in the position's favour: a long's higher, a short's lower."""
    return max(a, b, key=lambda x: sign * x)


@dataclass
class Position:
    opened_at: datetime
    entry_reason: str
    first_buy: float
    sign: int = 1  # 1 a long, -1 a short (_sign)
    # The most it may lock at once: Rules.max_margin, less past losses - never
    # more (profits are banked, not put back in) unless the rules compound.
    budget: float | None = None
    size: float = 0.0
    cost: float = 0.0  # the notional at entry of the size held
    margin: float = 0.0  # backing the size held
    peak_margin: float = 0.0  # the most locked at once - the cash it needed
    fees: float = 0.0  # the buys'
    slippage: float = 0.0  # Rules.slippage
    realized: float = 0.0  # the sells' PnL, net of their fees
    fills: list[Fill] = field(default_factory=list)
    # The grid's units held (price, size): every buy - the first, every dip
    # add and signal add (held_units, as live).
    units: list[tuple[float, float]] = field(default_factory=list)

    @property
    def entry(self) -> float:
        return self.cost / self.size

    def next_unwind(self, buffer: float) -> float | None:
        """The price the next unwind sells at (unwind_level, as live)."""
        return unwind_level(self.sign, self.units, buffer)

    def unwind(self, time: datetime, price: float, fee_rate: float) -> None:
        """Sells the next unwind's unit (unwound_unit, as live) at `price`."""
        unit = unwound_unit(self.sign, self.units)
        assert unit is not None
        self.units.remove(unit)
        self.sell(time, price, unit[1] / self.size, fee_rate, unit[0])

    def pnl_at(self, price: float, fee_rate: float) -> float:
        """The whole PnL closed at `price`: the sells' + the size held's, after fees."""
        held = self.sign * self.size * (price - self.entry) - self.size * price * fee_rate
        return self.realized + held - self.fees

    def sell(
        self,
        time: datetime,
        price: float,
        fraction: float,
        fee_rate: float,
        unit_price: float | None = None,
    ) -> None:
        """Sells `fraction` of the size held at `price` - the unit bought at
        `unit_price` (its profit on the fill: size x (price - unit_price),
        before fees); its share of the margin is released - the execution
        engine's partial close."""
        price *= 1 - self.sign * self.slippage
        sold = self.size * fraction
        released = self.margin * fraction
        self.realized += self.sign * sold * (price - self.entry) - sold * price * fee_rate
        profit = None if unit_price is None else self.sign * sold * (price - unit_price)
        self.fills.append(Fill(time, price, released, sold * price, "sell", profit))
        self.size -= sold
        self.cost -= self.cost * fraction
        self.margin -= released

    def buy(
        self,
        time: datetime,
        price: float,
        margin: float,
        leverage: float,
        fee_rate: float,
    ) -> None:
        """Every buy is a unit of the grid - the first, a dip add (the margin
        left down to ADD_AT_MARGIN_LEFT) or a signal add."""
        price *= 1 + self.sign * self.slippage
        if not self.fills:
            self.first_buy = price  # its fill
        notional = margin * leverage
        self.units.append((price, notional / price))
        self.fills.append(Fill(time, price, margin, notional))
        self.size += notional / price
        self.cost += notional
        self.margin += margin
        self.peak_margin = max(self.peak_margin, self.margin)
        self.fees += notional * fee_rate

    def margin_left_at(self, share: float) -> float:
        """The price at which the margin left is down to `share` of it."""
        return self.entry - self.sign * self.margin * (1 - share) / self.size

    def liquidation(self, maintenance: float, notional: float | None = None) -> float:
        """The price at which the exchange liquidates: the equity (margin
        plus the PnL of the size held) down to `notional` x the notional
        there - the exchange's maintenance margin; without it, the margin
        left down to `maintenance` of it, the execution engine's rule
        (app/execution_engine/demo.py)."""
        if notional is None:
            return self.margin_left_at(maintenance)
        return (self.size * self.entry - self.sign * self.margin) / (
            self.size * (1 - self.sign * notional)
        )


@dataclass(frozen=True)
class FillState:
    """The position right after a fill."""

    margin: float  # backing the size held
    entry: float  # the average entry
    leverage: float  # the whole position's: notional at entry / margin
    liquidation: float
    pnl_usd: float  # at the buy's price, before fees


def states_after(
    fills: list[Fill], maintenance: float, notional: float | None = None, short: bool = False
) -> list[FillState]:
    """The position after each of its fills (the first entry, then the adds
    and unwinds). `maintenance` /
    `notional`: Position.liquidation's; `short`: a short paper's position."""
    pos = Position(fills[0].time, "", fills[0].price, -1 if short else 1)
    out: list[FillState] = []
    for f in fills:
        if f.side == "sell":
            pos.sell(f.time, f.price, f.notional / f.price / pos.size, 0.0)
        else:
            pos.buy(f.time, f.price, f.margin, f.notional / f.margin, 0.0)
        out.append(
            FillState(
                pos.margin,
                pos.entry,
                pos.cost / pos.margin,
                pos.liquidation(maintenance, notional),
                pos.sign * pos.size * (f.price - pos.entry),
            )
        )
    return out


@dataclass(frozen=True)
class AveragingTrade:
    opened_at: datetime
    entry_reason: str
    entry_price: float  # the average entry
    give_up_price: float | None  # max_drawdown's level, None without it
    fills: tuple[Fill, ...]  # the first entry, then every add and sale
    margin: float  # the peak margin: the most locked at once
    closed_at: datetime
    close_price: float
    exit_reason: str
    pnl_usd: float  # net of every fee
    direction: str = "long"

    @property
    def adds(self) -> int:
        return sum(f.side == "buy" for f in self.fills) - 1

    @property
    def margin_return_pct(self) -> float:
        return self.pnl_usd / self.margin * 100


def _close(
    pos: Position, bar: Bar, price: float, reason: str, rules: Rules, fee_rate: float
) -> AveragingTrade:
    if reason != OPEN_AT_END:  # a close fills - valued at the last close, it doesn't
        price *= 1 - pos.sign * pos.slippage
    fees = pos.fees + pos.size * price * fee_rate
    pnl = pos.sign * pos.size * (price - pos.entry) - fees + pos.realized
    if reason == LIQUIDATION_EXIT and rules.maintenance_notional is not None:
        # The exchange keeps what's left of the margin (to its insurance
        # fund): the whole margin is lost - its sells' PnL kept.
        pnl = pos.realized - pos.margin - pos.fees
    return AveragingTrade(
        pos.opened_at,
        pos.entry_reason,
        pos.entry,
        None if rules.max_drawdown is None else _give_up_price(pos, rules.max_drawdown),
        tuple(pos.fills),
        pos.peak_margin,
        bar.time,
        price,
        reason,
        pnl,
        direction="short" if pos.sign == -1 else "long",
    )


def _give_up_price(pos: Position, max_drawdown: float) -> float:
    """max_drawdown's level: that far against the first buy."""
    return pos.first_buy * (1 - pos.sign * max_drawdown)


def _can_add(pos: Position, margin: float) -> bool:
    """An add of `margin` stays within the position's budget (the cash a real
    account has)."""
    return pos.budget is None or pos.margin + margin <= pos.budget


def _down_to_low(pos: Position, bar: Bar, rules: Rules, fee_rate: float) -> AveragingTrade | None:
    """The candle's way down to its low: the adds, the give-ups and the
    liquidation it reaches, highest price first (an exit before an add at
    the same price); each fills at its level, or at the open past it. Past
    the budget no add comes - the dip runs on to a give-up: the automatic
    one (OUT_OF_MARGIN_EXIT) comes before the execution engine's liquidation,
    which only a gap past both reaches - at the open, the give-up's fill. The
    exchange's (`maintenance_notional`) can come first at a high leverage.
    A short's: the way up to its high, lowest price first."""
    sign = pos.sign
    adverse = bar.low if sign == 1 else bar.high
    while True:
        # Where the exchange's maintenance margin liquidates early, the add and
        # the give-up move up with it (margin_levels) - the add before it.
        add_at, give_up_at = margin_levels(pos.margin, pos.cost, rules.maintenance_notional)
        events = [
            (pos.margin_left_at(give_up_at), 2, OUT_OF_MARGIN_EXIT),
            (pos.liquidation(rules.maintenance, rules.maintenance_notional), 1, LIQUIDATION_EXIT),
        ]
        if rules.max_drawdown is not None:
            events.append((_give_up_price(pos, rules.max_drawdown), 3, MAX_DRAWDOWN_EXIT))
        if _can_add(pos, rules.add_size):
            events.append((pos.margin_left_at(add_at), 0, ""))
        reached = [e for e in events if sign * (e[0] - adverse) >= 0]
        if not reached:
            return None
        # The first reached on the way (an exit before an add at the same price).
        level, _, reason = max(reached, key=lambda e: (sign * e[0], e[1]))
        fill = _worse(sign, level, bar.open)
        if reason:
            return _close(pos, bar, fill, reason, rules, fee_rate)
        pos.buy(bar.time, fill, rules.add_size, rules.add_leverage, fee_rate)


def in_trend(bars: list[Bar], trades: Sequence[SimTrade], direction: str = "long") -> set[datetime]:
    """The candles the strategy's own trade in `direction` is still open at
    the close of - opened on it or before, sold after it (or never): its
    trend lasts."""
    times = [b.time for b in bars]
    held: set[datetime] = set()
    for t in trades:
        if t.direction != direction:
            continue
        sold = None if t.exit_reason == OPEN_AT_END else t.closed_at
        end = len(times) if sold is None else bisect_left(times, sold)
        held.update(times[bisect_left(times, t.opened_at) : end])
    return held


def simulate(
    bars: list[Bar],
    entries: list[SimTrade],
    rules: Rules,
    fee_rate: float = 0.0,
    start: datetime | None = None,
    signals_held: Sequence[SimTrade] = (),
) -> list[AveragingTrade]:
    """From `start`, one position at a time; `entries`: the strategy's
    trades - their long entries open the positions, their exits are the
    sell signals; `signals_held`: its long signals on any candle (its own
    trade held or not) - entries and signal adds too."""
    directions = rules.directions
    signals: dict[str, dict[datetime, SimTrade]] = {d: {} for d in directions}
    sells: dict[str, dict[datetime, SimTrade]] = {d: {} for d in directions}
    for t in signals_held:
        if t.direction in signals:
            signals[t.direction].setdefault(t.opened_at, t)
    for t in entries:
        if t.direction in signals:
            signals[t.direction].setdefault(t.opened_at, t)
            if t.closed_at is not None and t.exit_reason != OPEN_AT_END:
                sells[t.direction].setdefault(t.closed_at, t)
    # Reopening after an intraday take-profit: where the strategy's trend lasts.
    reopening = rules.intraday and rules.reopen
    trend = {d: in_trend(bars, entries, d) if reopening else set() for d in directions}
    trades: list[AveragingTrade] = []
    pos: Position | None = None
    budget = rules.max_margin  # the cash: grows with every win, shrinks with every loss

    def cap(cash: float | None) -> float | None:
        """A new position's budget: the cash, at most the max margin (all of
        it when compounding)."""
        if cash is None or rules.max_margin is None:
            return None
        return cash if rules.compound else min(cash, rules.max_margin)

    def open_at(time: datetime, reason: str, price: float, sign: int) -> Position:
        """A new position on the cash."""
        return Position(time, reason, price, sign, cap(budget), slippage=rules.slippage)

    for bar in bars:
        if pos is not None:
            sign = pos.sign
            direction = "short" if sign == -1 else "long"
            signal = signals[direction].get(bar.time)  # its own direction's only
            favourable = bar.high if sign == 1 else bar.low  # a short's way down
            buys = len(pos.fills)
            closed = _down_to_low(pos, bar, rules, fee_rate)
            # On the way up, each unit but the lowest is sold once it's in profit
            # - not in a candle that added units: its high may have come first.
            added = len(pos.fills) > buys
            unwinds = closed is None and not added
            buffer = float(unwind_buffer(Decimal(str(fee_rate))))
            level = pos.next_unwind(buffer) if unwinds else None
            while level is not None and sign * (favourable - level) >= 0:
                pos.unwind(bar.time, _better(sign, level, bar.open), fee_rate)
                level = pos.next_unwind(buffer)
            sell = sells[direction].get(bar.time)
            margin = pos.margin
            if rules.intraday:
                # The take-profit at once: the price where the whole position's PnL
                # reaches it - not in a candle that added units, as the unwinds.
                gain = rules.take_profit * margin - pos.realized
                target = pos.entry + sign * gain / pos.size
                if closed is None and not added and sign * (favourable - target) >= 0:
                    fill = _better(sign, target, bar.open)
                    closed = _close(pos, bar, fill, TAKE_PROFIT_EXIT, rules, fee_rate)
            elif closed is None and sell is not None and sell.close_price is not None:
                # The whole position: its unwinds' realized PnL + the size held (as live).
                pnl = pos.realized + sign * pos.size * (sell.close_price - pos.entry)
                if pnl >= rules.take_profit * margin:
                    reason = f"{TAKE_PROFIT_EXIT}:{sell.exit_reason}"
                    closed = _close(pos, bar, sell.close_price, reason, rules, fee_rate)
            if closed is not None:
                trades.append(closed)
                pos = None
                if budget is not None:
                    budget += closed.pnl_usd
                funded = budget is None or budget >= rules.initial_size
                reopen = closed.exit_reason == TAKE_PROFIT_EXIT and bar.time in trend[direction]
                if reopen and funded:
                    # The trend still on: a fresh position at the candle's close.
                    pos = open_at(bar.time, REOPEN_IN_TREND, bar.close, sign)
                    pos.buy(bar.time, bar.close, rules.initial_size, rules.leverage, fee_rate)
            elif signal is not None and _can_add(pos, rules.initial_size):
                # A signal add, sized like the first entry.
                pos.buy(bar.time, signal.entry_price, rules.initial_size, rules.leverage, fee_rate)
        funded = budget is None or budget >= rules.initial_size
        # Flat: the first direction signalling here opens one (both: a long first).
        signal = next((signals[d][bar.time] for d in directions if bar.time in signals[d]), None)
        if pos is None and signal is not None and funded and (start is None or bar.time >= start):
            price = signal.entry_price
            pos = open_at(bar.time, signal.entry_reason, price, _sign(signal.direction))
            pos.buy(bar.time, price, rules.initial_size, rules.leverage, fee_rate)
    if pos is not None and bars:
        trades.append(_close(pos, bars[-1], bars[-1].close, OPEN_AT_END, rules, fee_rate))
    return trades


def rules_of(paper: Paper, limits: Limits | None = None) -> Rules:
    """The paper's averaging rules; with the exchange's `limits` for its
    asset, the leverages capped at its max leverage and the liquidation at
    its maintenance margin - as the exchange would."""

    def capped(leverage: float) -> float:
        return leverage if limits is None else min(leverage, limits.max_leverage)

    def share(value: Decimal | None) -> float:
        assert value is not None  # required on an averaging paper (app/api/papers.py)
        return float(value)

    def optional(value: Decimal | None) -> float | None:
        return None if value is None else float(value)

    initial = share(paper.initial_size_usd)
    return Rules(
        leverage=capped(float(paper.leverage)),
        initial_size=initial,
        add_leverage=capped(share(paper.add_leverage)),
        add_size=float(paper.add_size_usd) if paper.add_size_usd is not None else initial,
        take_profit=share(paper.take_profit_pct),
        max_drawdown=optional(paper.max_drawdown_pct),
        maintenance=settings.maintenance_margin_pct,
        max_margin=optional(paper.max_margin_usd),
        intraday=bool(paper.intraday),
        reopen=bool(paper.reopen_in_trend),
        compound=bool(paper.compound_margin),
        maintenance_notional=None if limits is None else limits.maintenance_margin,
        direction=paper.direction,
        slippage=FILL_SLIPPAGE,
    )


async def backtest_paper(paper: Paper, start: datetime | None) -> list[AveragingTrade]:
    trades_of = STRATEGY_TRADES.get(paper.executor)
    if trades_of is None:
        logger.info("paper %d: %s has no backtest - no entries to replay", paper.id, paper.executor)
        return []
    bars = await load_bars(paper)
    rules = rules_of(paper, await market_limits(paper.asset))
    start = start or paper.backtest_start
    signals_of = ENTRY_SIGNALS.get(paper.executor)
    fee_rate = float(await maker_fee_rate())
    simulated = simulate(
        bars,
        trades_of(paper, bars, start),
        rules,
        fee_rate,
        start,
        signals_of(paper, bars) if signals_of is not None else [],
    )
    # A position still open on the last candle is stored too (`open_at_end`, at
    # the last close - unrealized); the totals count the closed ones.
    trades = simulated
    closed = [t for t in trades if t.exit_reason != OPEN_AT_END]
    now = datetime.now(UTC)
    async with async_session() as session, session.begin():
        # Its fills go with it (ON DELETE CASCADE).
        await session.execute(delete(BacktestTrade).where(BacktestTrade.paper_id == paper.id))
        for t in trades:
            row = BacktestTrade(
                paper_id=paper.id,
                direction=t.direction,
                opened_at=t.opened_at,
                entry_price=Decimal(str(t.entry_price)),
                stop_loss_price=None if t.give_up_price is None else Decimal(str(t.give_up_price)),
                closed_at=t.closed_at,
                close_price=Decimal(str(t.close_price)),
                entry_reason=f"{t.entry_reason} +{t.adds} adds",
                exit_reason=t.exit_reason,
                return_pct=Decimal(str(round(t.margin_return_pct / rules.leverage, 6))),
                margin_usd=Decimal(str(round(t.margin, 6))),
                pnl_usd=Decimal(str(round(t.pnl_usd, 6))),
                created_at=now,
            )
            session.add(row)
            await session.flush()
            session.add_all(
                BacktestFill(
                    backtest_trade_id=row.id,
                    filled_at=f.time,
                    price=Decimal(str(f.price)),
                    margin_usd=Decimal(str(f.margin)),
                    notional_usd=Decimal(str(f.notional)),
                    side=f.side,
                    pnl_usd=None if f.pnl is None else Decimal(str(round(f.pnl, 6))),
                )
                for f in t.fills
            )
    logger.info(
        "paper %d (%s %s averaging on %s): %d closed positions, %d won, %d given up, "
        "%d liquidated, "
        "net %+.2f USD, most margin locked at once %.2f USD%s",
        paper.id,
        paper.asset,
        paper.timeframe,
        paper.executor,
        len(closed),
        sum(t.pnl_usd > 0 for t in closed),
        sum(t.exit_reason in (MAX_DRAWDOWN_EXIT, OUT_OF_MARGIN_EXIT) for t in closed),
        sum(t.exit_reason == LIQUIDATION_EXIT for t in closed),
        sum(t.pnl_usd for t in closed),
        max((t.margin for t in trades), default=0.0),
        "".join(
            f"; open: {t.adds} adds, {t.margin:.2f} USD peak margin, "
            f"{t.pnl_usd:+.2f} USD unrealized"
            for t in trades
            if t.exit_reason == OPEN_AT_END
        ),
    )
    return trades


async def main() -> None:
    start = datetime.fromisoformat(sys.argv[1]).replace(tzinfo=UTC) if len(sys.argv) > 1 else None
    async with async_session() as session:
        papers = (await session.scalars(select(Paper).where(Paper.kind == "averaging"))).all()
    if not papers:
        logger.info("no averaging papers - nothing to backtest")
    for paper in papers:
        await backtest_paper(paper, start)


if __name__ == "__main__":
    run_service("backtest", main)
