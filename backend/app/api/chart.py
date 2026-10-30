"""One paper's chart: candles at its timeframe, its positions with every fill,
and the swing labels (docs/api.md). The overlays (swings, VWAP, trend
bands, Supertrend, Keltner signals) are computed in a worker thread - the event loop keeps
answering meanwhile - and cached until the next candle closes."""

import asyncio
from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import NamedTuple

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.portfolio import exit_levels
from app.backtest.averaging import states_after
from app.backtest.bars import Fill
from app.backtest.models import BacktestFill, BacktestTrade
from app.config import settings
from app.db import async_session
from app.execution_engine.demo import unrealized_pnl
from app.execution_engine.models import Order, Position, TradingDecision
from app.executors.keltner import KeltnerStrategy
from app.executors.keltner_signals import keltner_signals
from app.executors.supertrend import signals as supertrend_signals
from app.executors.swings import find_swings
from app.executors.trend_bands import CALC_BARS, trend_bands
from app.executors.vwap_signals import lines, signal_at
from app.feature_engine.engine import INTERVAL_MINUTES
from app.market_data.limits import market_limits
from app.market_data.models import Candle
from app.papers.models import Paper

router = APIRouter()

# The most candles a chart reaches back to show the whole of a position that
# opened before its window (15m: ~208 days).
MAX_CHART_CANDLES = 20000
# The overlays of this many charts are kept (by paper, window and last closed candle).
OVERLAY_CACHE_SIZE = 16


class ChartCandle(NamedTuple):
    """A candle's columns the chart uses - plain rows, not ORM objects (fast to load)."""

    open_time: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal


_CANDLE_COLUMNS = (
    Candle.open_time,
    Candle.open,
    Candle.high,
    Candle.low,
    Candle.close,
    Candle.volume,
)


class CandleOut(BaseModel):
    time: datetime  # open time
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal


class SwingOut(BaseModel):
    kind: str  # HH | LL | HL | LH
    price: float
    time: datetime  # the pivot candle's open time
    confirmed_at: datetime  # open time of the candle that confirmed it


class VwapPointOut(BaseModel):
    time: datetime  # the candle's open time
    vwap: float | None  # None before the window's first full session
    ema: float
    signal: str | None  # long (BUY) | short (SELL) at this candle's close


class BandPointOut(BaseModel):
    time: datetime  # the candle's open time
    state: int  # 1 bullish, -1 bearish, 0 before the first cross
    band: float | None  # the lower band while bullish, the upper one while bearish
    inner: float | None  # the band's inner edge (1 ATR inside): the value zone
    signal: str | None  # long (break-up) | short (break-down) at this candle's close


class SupertrendPointOut(BaseModel):
    time: datetime  # the candle's open time
    line: float | None  # the up band in an uptrend, the dn band in a downtrend
    trend: int | None  # 1 up, -1 down; None without a trendline yet
    signal: str | None  # long (Buy) | short (Sell) at this candle's close


class KeltnerPointOut(BaseModel):
    time: datetime  # the candle's open time
    signal: str  # long (Buy) | short (Sell) at this candle's close


class FillOut(BaseModel):
    time: datetime
    side: str  # buy | sell
    size: Decimal
    price: Decimal | None


class ChartPositionOut(BaseModel):
    id: int
    mode: str
    direction: str
    size: Decimal  # still open (closed: the last part closed)
    entry_price: Decimal
    close_price: Decimal | None
    initial_margin_usd: Decimal
    realized_pnl_usd: Decimal | None  # every close so far, partial ones too
    unrealized_pnl_usd: Decimal | None  # open only, at the last candle close
    entry_reason: str | None  # the reason of the decision that opened it
    stop_loss_price: Decimal | None  # from the entry decision
    take_profit_price: Decimal | None
    exit_reason: str | None
    opened_at: datetime
    closed_at: datetime | None
    fills: list[FillOut]


class BacktestFillOut(BaseModel):
    time: datetime  # the candle it filled in (open time)
    price: Decimal
    margin_usd: Decimal  # a sell: the margin it released
    notional_usd: Decimal
    # buy (the first entry or an add) | sell (a unit sold).
    side: str
    # A sell: its unit's profit (before fees).
    realized_pnl_usd: Decimal | None
    # The position right after this fill (app/backtest/averaging.py's states_after).
    total_margin_usd: float
    avg_entry: float
    leverage: float
    liquidation_price: float
    pnl_usd: float  # at this buy's price, before fees


class BacktestTradeOut(BaseModel):
    direction: str
    opened_at: datetime
    entry_price: Decimal
    stop_loss_price: Decimal | None  # None: no stop-loss (VWAP)
    closed_at: datetime
    close_price: Decimal
    entry_reason: str | None
    exit_reason: str
    return_pct: Decimal  # net of fees, % of the entry notional
    # An averaging paper's position: all the margin put in, the PnL net of fees,
    # and its buys (the first entry, then every add); null / empty otherwise.
    margin_usd: Decimal | None
    pnl_usd: Decimal | None
    fills: list[BacktestFillOut]


class PaperChartOut(BaseModel):
    paper_id: int
    asset: str
    timeframe: str
    executor: str
    kind: str
    candles: list[CandleOut]
    swings: list[SwingOut]
    # VWAP + EMA 9 and their BUY / SELL per closed candle.
    vwap: list[VwapPointOut]
    # BigBeluga trend bands and their break signals per closed candle.
    bands: list[BandPointOut]
    # The Supertrend and its Buy / Sell per closed candle - on every paper's chart.
    supertrend: list[SupertrendPointOut]
    # A Keltner paper's Buy / Sell candles (signals only); empty otherwise.
    keltner: list[KeltnerPointOut]
    positions: list[ChartPositionOut]
    # Temporary: the executor's backtest (docs/vwap-strategy-engine.md#backtest).
    backtest: list[BacktestTradeOut]


def _fills_out(
    rows: list[BacktestFill], notional: float | None, short: bool
) -> list[BacktestFillOut]:
    """An averaging position's fills, each with the position's state after it
    (`notional`: the exchange's maintenance margin, liquidating there;
    `short`: a short position's)."""
    if not rows:
        return []
    fills = [
        Fill(r.filled_at, float(r.price), float(r.margin_usd), float(r.notional_usd), r.side)
        for r in rows
    ]
    states = states_after(fills, settings.maintenance_margin_pct, notional, short)
    return [
        BacktestFillOut(
            time=r.filled_at,
            price=r.price,
            margin_usd=r.margin_usd,
            notional_usd=r.notional_usd,
            side=r.side,
            realized_pnl_usd=r.pnl_usd,
            total_margin_usd=s.margin,
            avg_entry=s.entry,
            leverage=s.leverage,
            liquidation_price=s.liquidation,
            pnl_usd=s.pnl_usd,
        )
        for r, s in zip(rows, states, strict=True)
    ]


async def _load_candles(
    session: AsyncSession,
    paper: Paper,
    limit: int,
    since: datetime | None = None,
    before: datetime | None = None,
    oldest: bool = False,
) -> list[ChartCandle]:
    """The paper's newest `limit` candles from `since` and before `before`
    (`oldest`: the oldest ones instead), oldest first."""
    query = select(*_CANDLE_COLUMNS).where(
        Candle.asset == paper.asset, Candle.interval == paper.timeframe
    )
    if since is not None:
        query = query.where(Candle.open_time >= since)
    if before is not None:
        query = query.where(Candle.open_time < before)
    order = Candle.open_time.asc() if oldest else Candle.open_time.desc()
    rows = (await session.execute(query.order_by(order).limit(limit))).all()
    return [ChartCandle(*r) for r in (rows if oldest else reversed(rows))]


def _candles_out(candles: list[ChartCandle]) -> list[CandleOut]:
    return [
        CandleOut(time=c.open_time, open=c.open, high=c.high, low=c.low, close=c.close)
        for c in candles
    ]


def _step(timeframe: str) -> timedelta:
    return timedelta(minutes=INTERVAL_MINUTES[timeframe])


async def _entry_reasons(position_ids: list[int]) -> dict[int, str]:
    """The reason of the entry decision that opened each position."""
    if not position_ids:
        return {}
    async with async_session() as session:
        rows = await session.execute(
            select(Order.position_id, TradingDecision.reason)
            .join(TradingDecision, TradingDecision.order_id == Order.id)
            .where(Order.position_id.in_(position_ids), TradingDecision.signal == "enter")
        )
        return {pid: reason for pid, reason in rows.all() if pid is not None}


def _swings(series: list[ChartCandle], keep: range) -> list[SwingOut]:
    """The swings found over `series` (closed candles), those pivoting on the
    candles in `keep`."""
    highs, lows = [float(c.high) for c in series], [float(c.low) for c in series]
    return [
        SwingOut(
            kind=s.kind,
            price=s.price,
            time=series[s.pivot_index].open_time,
            confirmed_at=series[s.confirm_index].open_time,
        )
        for s in find_swings(highs, lows)
        if s.pivot_index in keep
    ]


def _supertrend(direction: str, series: list[ChartCandle], keep: range) -> list[SupertrendPointOut]:
    """Every paper's Supertrend - the one a Supertrend paper trades (on the
    lower trendline for a long paper, the upper for the others) - computed
    over `series` (closed candles), on the candles in `keep`."""
    st = supertrend_signals(
        [float(c.high) for c in series],
        [float(c.low) for c in series],
        [float(c.close) for c in series],
        "long" if direction == "long" else "short",
    )
    return [
        SupertrendPointOut(
            time=series[j].open_time,
            line=st.line[j],
            trend=st.trend[j],
            signal="long" if st.buy[j] else "short" if st.sell[j] else None,
        )
        for j in keep
    ]


def _keltner(executor: str, series: list[ChartCandle], keep: range) -> list[KeltnerPointOut]:
    """A Keltner paper's Buy / Sell candles in `keep`, computed over `series`
    (closed candles); none for the others."""
    if executor != KeltnerStrategy.name:
        return []
    ks = keltner_signals(
        [float(c.high) for c in series],
        [float(c.low) for c in series],
        [float(c.close) for c in series],
    )
    return [
        KeltnerPointOut(time=series[j].open_time, signal="long" if ks.buy[j] else "short")
        for j in keep
        if ks.buy[j] or ks.sell[j]
    ]


def _bands(series: list[ChartCandle], keep: range) -> list[BandPointOut]:
    """The trend bands computed over `series` (closed candles - the state
    depends on the whole path), on the candles in `keep`."""
    b = trend_bands(
        [float(c.high) for c in series],
        [float(c.low) for c in series],
        [float(c.close) for c in series],
        [float(c.volume) for c in series],
    )
    out: list[BandPointOut] = []
    for j in keep:
        state, a = b.state[j], b.atr[j]
        band = b.lower[j] if state == 1 else b.upper[j] if state == -1 else None
        out.append(
            BandPointOut(
                time=series[j].open_time,
                state=state,
                band=band,
                inner=None if band is None or a is None else band + state * a,
                signal="long" if b.break_up[j] else "short" if b.break_dn[j] else None,
            )
        )
    return out


@dataclass(frozen=True)
class _Overlays:
    swings: list[SwingOut]
    vwap: list[VwapPointOut]
    bands: list[BandPointOut]
    supertrend: list[SupertrendPointOut]
    keltner: list[KeltnerPointOut]


def _vwap(closed: list[ChartCandle]) -> list[VwapPointOut]:
    times = [c.open_time for c in closed]
    closes = [float(c.close) for c in closed]
    ln = lines(
        times,
        [float(c.high) for c in closed],
        [float(c.low) for c in closed],
        closes,
        [float(c.volume) for c in closed],
    )
    # The window starts mid-session: its first day's VWAP would be partial.
    first_day = next((k for k in range(1, len(times)) if times[k].date() != times[0].date()), 0)
    return [
        VwapPointOut(
            time=t,
            vwap=ln.vwap[k] if k >= first_day else None,
            ema=ln.ema[k],
            signal=signal_at(closes, ln, k) if k > first_day else None,
        )
        for k, t in enumerate(times)
    ]


def _overlays(
    executor: str, direction: str, closed: list[ChartCandle], older: list[ChartCandle]
) -> _Overlays:
    """Every overlay on every chart, whatever the paper's executor: over the
    window's closed candles; the bands, the Supertrend and the Keltner
    signals over the `older` history (their state depends on the whole
    path), on the window's candles.
    CPU-bound - run in a worker thread."""
    keep = range(len(older) - len(closed), len(older))
    return _Overlays(
        _swings(closed, range(len(closed))),
        _vwap(closed),
        _bands(older, keep),
        _supertrend(direction, older, keep),
        _keltner(executor, older, keep),
    )


_overlay_cache: OrderedDict[tuple[object, ...], _Overlays] = OrderedDict()


async def _cached_overlays(
    paper: Paper, closed: list[ChartCandle], older: list[ChartCandle]
) -> _Overlays:
    """The overlays, computed once per window and last closed candle."""
    key = (
        paper.asset,
        paper.timeframe,
        paper.executor,
        paper.direction,
        older[0].open_time,
        closed[0].open_time,
        closed[-1].open_time,
    )
    cached = _overlay_cache.get(key)
    if cached is not None:
        _overlay_cache.move_to_end(key)
        return cached
    overlays = await asyncio.to_thread(_overlays, paper.executor, paper.direction, closed, older)
    _overlay_cache[key] = overlays
    while len(_overlay_cache) > OVERLAY_CACHE_SIZE:
        _overlay_cache.popitem(last=False)
    return overlays


@router.get("/papers/{paper_id}/chart", response_model=PaperChartOut)
async def paper_chart(
    paper_id: int, limit: int = Query(default=500, ge=50, le=6000)
) -> PaperChartOut:
    async with async_session() as session:
        paper = await session.get(Paper, paper_id)
        if paper is None:
            raise HTTPException(status_code=404, detail=f"no paper {paper_id}")
        # The trend bands' state depends on the whole path: computed over CALC_BARS.
        history = await _load_candles(session, paper, max(limit, CALC_BARS))
        candles = history[-limit:]
        # The overlays are computed over this window only, even when the candles
        # reach further back for an older position - fast enough for the chart.
        window = candles
        since = candles[0].open_time if candles else None
        if since is not None:
            # A position in the window that opened before it: reach back to its
            # open, so all its fills sit on candles (at most MAX_CHART_CANDLES).
            opened = [
                await session.scalar(
                    select(func.min(BacktestTrade.opened_at)).where(
                        BacktestTrade.paper_id == paper.id, BacktestTrade.closed_at >= since
                    )
                ),
                await session.scalar(
                    select(func.min(Position.opened_at)).where(
                        Position.paper_id == paper.id,
                        or_(Position.closed_at.is_(None), Position.closed_at >= since),
                    )
                ),
            ]
            earliest = min((t for t in opened if t is not None), default=None)
            if earliest is not None and earliest < since:
                candles = await _load_candles(
                    session, paper, MAX_CHART_CANDLES, earliest - _step(paper.timeframe)
                )
                since = candles[0].open_time
        position_filter = [Position.paper_id == paper.id]
        if since is not None:
            position_filter.append(or_(Position.closed_at.is_(None), Position.closed_at >= since))
        positions = (
            await session.scalars(
                select(Position).where(*position_filter).order_by(Position.opened_at)
            )
        ).all()
        # Every backtest trade, not only the window's: the summary covers them all
        # (the chart draws the ones on its candles).
        backtest = (
            await session.scalars(
                select(BacktestTrade)
                .where(BacktestTrade.paper_id == paper.id)
                .order_by(BacktestTrade.opened_at)
            )
        ).all()
        backtest_fills = (
            await session.scalars(
                select(BacktestFill)
                .where(BacktestFill.backtest_trade_id.in_([t.id for t in backtest]))
                .order_by(BacktestFill.filled_at, BacktestFill.id)
            )
        ).all()
        orders = (
            await session.scalars(
                select(Order)
                .where(Order.position_id.in_([p.id for p in positions]))
                .order_by(Order.created_at)
            )
        ).all()
        candles_out = _candles_out(candles)

    # Same input as the executor: closed candles (the newest one is forming).
    closed = window[:-1]
    overlays = (
        await _cached_overlays(paper, closed, history[:-1])
        if closed
        else _Overlays([], [], [], [], [])
    )

    last_close = candles[-1].close if candles else None
    sl_tp = await exit_levels([p.id for p in positions])
    entry_reasons = await _entry_reasons([p.id for p in positions])
    fills: dict[int, list[FillOut]] = {}
    for o in orders:
        if o.position_id is not None:
            fills.setdefault(o.position_id, []).append(
                FillOut(time=o.created_at, side=o.side, size=o.size, price=o.fill_price)
            )
    limits = await market_limits(paper.asset)
    maintenance = None if limits is None else limits.maintenance_margin
    # Each trade's fills, grouped once - not a scan of every fill per trade.
    fills_of: dict[int, list[BacktestFill]] = {}
    for f in backtest_fills:
        fills_of.setdefault(f.backtest_trade_id, []).append(f)
    return PaperChartOut(
        paper_id=paper.id,
        asset=paper.asset,
        timeframe=paper.timeframe,
        executor=paper.executor,
        kind=paper.kind,
        candles=candles_out,
        swings=overlays.swings,
        vwap=overlays.vwap,
        bands=overlays.bands,
        supertrend=overlays.supertrend,
        keltner=overlays.keltner,
        positions=[
            ChartPositionOut(
                id=p.id,
                mode=p.mode,
                direction=p.direction,
                size=p.size,
                entry_price=p.entry_price,
                close_price=p.close_price,
                initial_margin_usd=p.initial_margin_usd,
                realized_pnl_usd=p.realized_pnl_usd,
                unrealized_pnl_usd=(
                    unrealized_pnl(p.direction, p.entry_price, last_close, p.size)
                    if p.closed_at is None and last_close is not None
                    else None
                ),
                entry_reason=entry_reasons.get(p.id),
                stop_loss_price=sl_tp.get(p.id, (None, None))[0],
                take_profit_price=sl_tp.get(p.id, (None, None))[1],
                exit_reason=p.exit_reason,
                opened_at=p.opened_at,
                closed_at=p.closed_at,
                fills=fills.get(p.id, []),
            )
            for p in positions
        ],
        backtest=[
            BacktestTradeOut(
                direction=t.direction,
                opened_at=t.opened_at,
                entry_price=t.entry_price,
                stop_loss_price=t.stop_loss_price,
                closed_at=t.closed_at,
                close_price=t.close_price,
                entry_reason=t.entry_reason,
                exit_reason=t.exit_reason,
                return_pct=t.return_pct,
                margin_usd=t.margin_usd,
                pnl_usd=t.pnl_usd,
                fills=_fills_out(fills_of.get(t.id, []), maintenance, t.direction == "short"),
            )
            for t in backtest
        ],
    )


# Candles after an older chunk that confirm the swings pivoting at
# its end (the chart already has them).
CHUNK_OVERLAP = 200


class CandleChunkOut(BaseModel):
    candles: list[CandleOut]
    # The overlays on the chunk's candles, as the first window's: computed from
    # CALC_BARS candles before it (the bands' whole path, the VWAP session).
    vwap: list[VwapPointOut]
    bands: list[BandPointOut]
    supertrend: list[SupertrendPointOut]  # every paper's
    keltner: list[KeltnerPointOut]  # a Keltner paper's
    swings: list[SwingOut]  # pivoting in the chunk


def _chunk_overlays(
    executor: str,
    direction: str,
    warmup: list[ChartCandle],
    chunk: list[ChartCandle],
    after: list[ChartCandle],
) -> _Overlays:
    """A chunk's overlays, computed from `warmup` before it (and `after`,
    confirming its last swings). CPU-bound - run in a worker thread."""
    series = [*warmup, *chunk]
    keep = range(len(warmup), len(series))
    swings = _swings([*series, *after], keep)
    closes = [float(c.close) for c in series]
    ln = lines(
        [c.open_time for c in series],
        [float(c.high) for c in series],
        [float(c.low) for c in series],
        closes,
        [float(c.volume) for c in series],
    )
    vwap = [
        VwapPointOut(
            time=series[k].open_time,
            vwap=ln.vwap[k],
            ema=ln.ema[k],
            signal=signal_at(closes, ln, k) if k > 0 else None,
        )
        for k in keep
    ]
    return _Overlays(
        swings,
        vwap,
        _bands(series, keep),
        _supertrend(direction, series, keep),
        _keltner(executor, series, keep),
    )


@router.get("/papers/{paper_id}/candles", response_model=CandleChunkOut)
async def paper_candles(
    paper_id: int, before: datetime, limit: int = Query(default=2000, ge=50, le=5000)
) -> CandleChunkOut:
    """The `limit` candles before `before` (oldest first) - the strategy
    chart's older history, loaded as it scrolls back - with every overlay of
    the first window on them: VWAP + EMA 9, the trend bands and the swings,
    computed from CALC_BARS candles before the chunk (and
    CHUNK_OVERLAP after it, confirming the swings at its end). Empty: no
    older candles."""
    async with async_session() as session:
        paper = await session.get(Paper, paper_id)
        if paper is None:
            raise HTTPException(status_code=404, detail=f"no paper {paper_id}")
        chunk = await _load_candles(session, paper, limit, before=before)
        if not chunk:
            return CandleChunkOut(
                candles=[],
                vwap=[],
                bands=[],
                supertrend=[],
                keltner=[],
                swings=[],
            )
        warmup = await _load_candles(session, paper, CALC_BARS, before=chunk[0].open_time)
        after = await _load_candles(session, paper, CHUNK_OVERLAP, since=before, oldest=True)
        chunk_out = _candles_out(chunk)
    overlays = await asyncio.to_thread(
        _chunk_overlays, paper.executor, paper.direction, warmup, chunk, after
    )
    return CandleChunkOut(
        candles=chunk_out,
        vwap=overlays.vwap,
        bands=overlays.bands,
        supertrend=overlays.supertrend,
        keltner=overlays.keltner,
        swings=overlays.swings,
    )
