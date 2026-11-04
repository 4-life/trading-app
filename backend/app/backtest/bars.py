"""The backtests' shared parts: a paper's stored candles as bars, where a
backtest starts (find_backtest_from), the simulated trade and an averaging
position's fill, and saving a backtest's trades to `backtest_trades`."""

import logging
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import NamedTuple

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.backtest.models import OPEN_AT_END, BacktestTrade
from app.db import async_session
from app.executors.paper_exits import PAPER_STOP_LOSS, PAPER_TAKE_PROFIT
from app.feature_engine.engine import INTERVAL_MINUTES
from app.market_data.models import Candle
from app.market_data.shock_state import detect, entry_blocked
from app.market_data.shocks import Shock
from app.papers.models import Paper
from app.system.exchange_api import maker_fee_rate

logger = logging.getLogger(__name__)

STOP_SLIPPAGE = 0.0005  # a stop fills this much (% of price) past its level
# A price first reached later than this before the last candle leaves too
# little to test: the whole history instead (find_backtest_from).
MIN_TESTED = timedelta(days=30)


@dataclass(frozen=True)
class Bar:
    time: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0  # the VWAP backtest's


@dataclass(frozen=True)
class Fill:
    """An averaging position's fill: a buy (the first entry or an add) or a
    sell (a unit sold)."""

    time: datetime
    price: float
    margin: float  # a sell: the margin it released
    notional: float
    side: str = "buy"
    # A sell: its unit's profit (size x (price - the unit's buy price), before
    # fees); a short's reduce / close: the PnL it realized, net of fees.
    pnl: float | None = None


@dataclass
class SimTrade:
    direction: str
    opened_at: datetime
    entry_price: float
    stop_loss_price: float | None  # None: a strategy without a stop-loss (VWAP)
    closed_at: datetime | None = None
    close_price: float | None = None
    exit_reason: str | None = None
    entry_reason: str = ""

    def return_pct(self, fees: float) -> float:
        """`fees`: entry + exit fee per unit of notional."""
        assert self.close_price is not None
        move = self.close_price / self.entry_price - 1
        return ((move if self.direction == "long" else -move) - fees) * 100


def exit_at(held: str, bar: Bar, reason: str) -> SimTrade:
    """A strategy exit of a `held` position at `bar`'s close - an averaging
    paper's sell signal (its executor's exit_signals)."""
    return SimTrade(held, bar.time, bar.close, None, bar.time, bar.close, reason)


def paper_exits(paper: Paper) -> tuple[float | None, float | None]:
    """A paper's own stop-loss and take-profit as floats (None: not set)."""
    sl, tp = paper.stop_loss_pct, paper.price_take_profit_pct
    return (None if sl is None else float(sl), None if tp is None else float(tp))


def with_paper_exits(
    trades: list[SimTrade],
    bars: list[Bar],
    stop_loss: float | None,
    take_profit: float | None,
) -> list[SimTrade]:
    """The strategy's trades cut at a paper's own stop-loss / take-profit
    (shares of the entry price, docs/papers.md#stop-loss-and-take-profit)
    where one is reached before the trade's own exit: from the candle after
    its entry to its exit's, inside each the stop first (worst case), then
    the take-profit - each at its level, at the open past it; a stop fills
    STOP_SLIPPAGE further. The trade's stop is the tighter of the two."""
    if stop_loss is None and take_profit is None:
        return trades
    index = {b.time: k for k, b in enumerate(bars)}
    out: list[SimTrade] = []
    for t in trades:
        first = index.get(t.opened_at)
        if first is None:
            out.append(t)
            continue
        last = index.get(t.closed_at, len(bars) - 1) if t.closed_at is not None else len(bars) - 1
        sign = 1 if t.direction == "long" else -1
        stop = None if stop_loss is None else t.entry_price * (1 - sign * stop_loss)
        take = None if take_profit is None else t.entry_price * (1 + sign * take_profit)
        own = t.stop_loss_price
        tighter = stop if own is None or stop is None else sign * max(sign * stop, sign * own)
        cut = replace(t, stop_loss_price=tighter if tighter is not None else own)
        for bar in bars[first + 1 : last + 1]:
            worst = bar.low if sign == 1 else bar.high
            best = bar.high if sign == 1 else bar.low
            if stop is not None and sign * worst <= sign * stop:
                fill = sign * min(sign * stop, sign * bar.open)
                fill *= 1 - sign * STOP_SLIPPAGE
                cut = replace(
                    cut, closed_at=bar.time, close_price=fill, exit_reason=PAPER_STOP_LOSS
                )
                break
            if take is not None and sign * best >= sign * take:
                fill = sign * max(sign * take, sign * bar.open)
                cut = replace(
                    cut, closed_at=bar.time, close_price=fill, exit_reason=PAPER_TAKE_PROFIT
                )
                break
        out.append(cut)
    return out


async def strategy_papers(executor: str) -> list[Paper]:
    """The executor's papers its own backtest covers - an averaging
    paper's backtest is app.backtest.averaging, on the executor's entry signals."""
    async with async_session() as session:
        rows = await session.scalars(
            select(Paper).where(Paper.executor == executor, Paper.kind != "averaging")
        )
        return list(rows.all())


async def load_bars(paper: Paper) -> list[Bar]:
    """The paper's stored candles, closed only - the newest one is still forming."""
    async with async_session() as session:
        candles = (
            await session.scalars(
                select(Candle)
                .where(Candle.asset == paper.asset, Candle.interval == paper.timeframe)
                .order_by(Candle.open_time)
            )
        ).all()
    return [
        Bar(
            c.open_time, float(c.open), float(c.high), float(c.low), float(c.close), float(c.volume)
        )
        for c in candles[:-1]
    ]


class BacktestFrom(NamedTuple):
    """Where a backtest or a sweep starts trading."""

    start: datetime | None  # None: no candles
    price: float | None  # the current price it was found at; None: not found by price


def find_backtest_from(bars: Sequence[Bar], manual: datetime | None) -> BacktestFrom:
    """`manual`, if given; else the earliest candle whose range holds the
    current price (the last close), so the price ends where it started and the
    market's rise or fall doesn't flatter the result; else, reached too
    recently (MIN_TESTED), the whole history."""
    if manual is not None:
        return BacktestFrom(manual, None)
    if not bars:
        return BacktestFrom(None, None)
    price = bars[-1].close
    first = next(b for b in bars if b.low <= price <= b.high)  # the last candle at the latest
    if bars[-1].time - first.time < MIN_TESTED:
        return BacktestFrom(bars[0].time, None)
    return BacktestFrom(first.time, price)


async def store_backtest_from(session: AsyncSession, paper: Paper, tested: BacktestFrom) -> None:
    """Records on the paper where its stored backtest started."""
    price = None if tested.price is None else Decimal(str(tested.price))
    await session.execute(
        update(Paper)
        .where(Paper.id == paper.id)
        .values(backtest_from=tested.start, backtest_from_price=price)
    )
    paper.backtest_from, paper.backtest_from_price = tested.start, price


async def backtest_shocks(paper: Paper, bars: list[Bar], start: datetime | None) -> list[Shock]:
    """The market shocks over a backtest's candles (from `start`) - the risk
    engine's entry block, as live (docs/market-shocks.md)."""
    if not bars:
        return []
    step = timedelta(minutes=INTERVAL_MINUTES[paper.timeframe])
    first = max(bars[0].time, start) if start is not None else bars[0].time
    async with async_session() as session:
        return await detect(session, paper.asset, paper.timeframe, first, bars[-1].time + step)


class HeldBack(NamedTuple):
    """An entry a market shock held back (the risk engine's rule)."""

    at: datetime  # its signal candle's close
    direction: str
    shock: Shock


def log_held_back(paper: Paper, held: list[HeldBack]) -> None:
    """The backtest log's line for each entry a shock held back."""
    for h in held:
        scope = "market" if h.shock.scope == "market" else paper.asset
        logger.info(
            "paper %d: %s entry at %s held back - %s %s (%s, detected %s)",
            paper.id,
            h.direction,
            h.at.strftime("%Y-%m-%d %H:%M"),
            scope,
            h.shock.kind,
            h.shock.text,
            h.shock.detected_at.strftime("%Y-%m-%d %H:%M"),
        )


def unblocked(
    trades: list[SimTrade], shocks: Sequence[Shock], step: timedelta
) -> tuple[list[SimTrade], list[HeldBack]]:
    """The trades the risk engine would have let open - none entered (at its
    signal candle's close) while a shock against it held entries back - and
    the ones it held back."""
    kept: list[SimTrade] = []
    held: list[HeldBack] = []
    for t in trades:
        at = t.opened_at + step
        shock = entry_blocked(shocks, t.direction, at)
        if shock is None:
            kept.append(t)
        else:
            held.append(HeldBack(at, t.direction, shock))
    return kept, held


async def save_trades(
    paper: Paper, simulated: list[SimTrade], bars: list[Bar], tested: BacktestFrom
) -> list[SimTrade]:
    """Replaces the paper's backtest rows with `simulated` (net of the
    provider's maker fees) and logs the totals. A trade still open on the
    last candle has no result yet - left out of the stored trades and every
    statistic. The entries a market shock held back (the risk engine's rule)
    are left out."""
    start = tested.start
    step = timedelta(minutes=INTERVAL_MINUTES[paper.timeframe])
    simulated, held = unblocked(simulated, await backtest_shocks(paper, bars, start), step)
    log_held_back(paper, held)
    trades = [t for t in simulated if t.exit_reason != OPEN_AT_END]
    fees = float(await maker_fee_rate()) * 2  # entry and exit
    now = datetime.now(UTC)
    async with async_session() as session, session.begin():
        await session.execute(delete(BacktestTrade).where(BacktestTrade.paper_id == paper.id))
        await store_backtest_from(session, paper, tested)
        session.add_all(
            BacktestTrade(
                paper_id=paper.id,
                direction=t.direction,
                opened_at=t.opened_at,
                entry_price=Decimal(str(t.entry_price)),
                stop_loss_price=(
                    None if t.stop_loss_price is None else Decimal(str(t.stop_loss_price))
                ),
                closed_at=t.closed_at,
                close_price=Decimal(str(t.close_price)),
                entry_reason=t.entry_reason,
                exit_reason=t.exit_reason,
                return_pct=Decimal(str(round(t.return_pct(fees), 6))),
                created_at=now,
            )
            for t in trades
        )
    wins = sum(t.return_pct(fees) > 0 for t in trades)
    logger.info(
        "paper %d (%s %s, trading from %s): %d trades, %d won, net %+.2f%% of price "
        "(x%s leverage = %+.1f%% of margin)",
        paper.id,
        paper.asset,
        paper.timeframe,
        start.date() if start else (bars[0].time.date() if bars else "-"),
        len(trades),
        wins,
        sum(t.return_pct(fees) for t in trades),
        paper.leverage,
        sum(t.return_pct(fees) for t in trades) * float(paper.leverage),
    )
    return trades
