"""The backtests' shared parts: a paper's stored candles as bars, the
simulated trade and an averaging position's fill, and saving a backtest's
trades to `backtest_trades`."""

import logging
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import delete, select

from app.backtest.models import OPEN_AT_END, BacktestTrade
from app.db import async_session
from app.executors.paper_exits import PAPER_STOP_LOSS, PAPER_TAKE_PROFIT
from app.market_data.models import Candle
from app.papers.models import Paper
from app.system.exchange_api import maker_fee_rate

logger = logging.getLogger(__name__)

STOP_SLIPPAGE = 0.0005  # a stop fills this much (% of price) past its level


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


async def save_trades(
    paper: Paper, simulated: list[SimTrade], bars: list[Bar], start: datetime | None
) -> list[SimTrade]:
    """Replaces the paper's backtest rows with `simulated` (net of the
    provider's maker fees) and logs the totals. A trade still open on the
    last candle has no result yet - left out of the stored trades and every
    statistic."""
    trades = [t for t in simulated if t.exit_reason != OPEN_AT_END]
    fees = float(await maker_fee_rate()) * 2  # entry and exit
    now = datetime.now(UTC)
    async with async_session() as session, session.begin():
        await session.execute(delete(BacktestTrade).where(BacktestTrade.paper_id == paper.id))
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
