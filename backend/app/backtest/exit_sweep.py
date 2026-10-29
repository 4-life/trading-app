"""A single paper's settings sweep (docs/papers.md#stop-loss-and-take-profit):
which leverage, stop-loss and take-profit do best on its strategy's trades.
The strategy's own trades are computed once; every EXIT_LEVERAGES (up to the
asset's max) x EXIT_STOP_LOSSES x EXIT_TAKE_PROFITS run cuts them at its
stop-loss / take-profit (with_paper_exits, as the paper's backtest does) and
compounds them at its leverage - each trade on the whole margin, as the
chart's summary - with the max drawdown. A trade reaching the exchange's
liquidation price (its maintenance margin, app/market_data/limits.py)
before its stop loses the whole margin - and with it the equity. Trading
over the paper's last PAPER_DAYS, split at SPLIT for train / test; the
position still open at the end is left out. One chunk per leverage."""

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from itertools import product

from app.backtest.bars import Bar, SimTrade, load_bars, with_paper_exits
from app.backtest.models import OPEN_AT_END
from app.backtest.sweep import (
    PAPER_DAYS,
    PAPER_LEVERAGES,
    SPLIT,
    SweepError,
    _pool,
    run_jobs,
    strategy_inputs,
)
from app.config import settings
from app.executors.paper_exits import PAPER_STOP_LOSS, PAPER_TAKE_PROFIT
from app.market_data.limits import market_limits
from app.papers.models import Paper
from app.system.exchange_api import maker_fee_rate

EXIT_STOP_LOSSES: tuple[float | None, ...] = (
    None, 0.005, 0.01, 0.015, 0.02, 0.03, 0.05, 0.075, 0.10,
)  # fmt: skip
EXIT_TAKE_PROFITS: tuple[float | None, ...] = (
    None, 0.01, 0.02, 0.03, 0.05, 0.075, 0.10, 0.15, 0.20, 0.30,
)  # fmt: skip


@dataclass(frozen=True)
class ExitJob:
    """One leverage of a single paper's sweep - every stop-loss x take-profit."""

    bars: list[Bar]
    trades: list[SimTrade]  # the strategy's own, uncut
    leverage: float
    # The exchange's maintenance margin, a share of the notional; None: not
    # stored - the margin left down to MAINTENANCE_MARGIN_PCT of it instead.
    maintenance: float | None
    fee_rate: float  # per side
    start: datetime
    split: datetime


def liquidation_price(
    direction: str, entry: float, leverage: float, maintenance: float | None
) -> float:
    """Where the exchange liquidates a position at `leverage`: its equity
    down to `maintenance` x the notional; without it, the margin left down
    to MAINTENANCE_MARGIN_PCT of the margin (the averaging backtest's rule)."""
    sign = 1 if direction == "long" else -1
    if maintenance is None:
        return entry * (1 - sign * (1 - settings.maintenance_margin_pct) / leverage)
    return entry * (1 - sign / leverage) / (1 - sign * maintenance)


def _liquidated(job: ExitJob, t: SimTrade, index: dict[datetime, int]) -> bool:
    """The price reached the liquidation before the trade's exit - with a
    stop the liquidation comes after, never."""
    sign = 1 if t.direction == "long" else -1
    liquidation = liquidation_price(t.direction, t.entry_price, job.leverage, job.maintenance)
    if t.stop_loss_price is not None and sign * t.stop_loss_price >= sign * liquidation:
        return False
    first, last = index[t.opened_at] + 1, index.get(t.closed_at or job.bars[-1].time, 0)
    worst = (b.low if sign == 1 else b.high for b in job.bars[first : last + 1])
    return any(sign * w <= sign * liquidation for w in worst)


def _compound(results: list[tuple[float, bool]], leverage: float) -> tuple[float, float]:
    """(return, max drawdown) in % of the margin over the trades' (net
    return of price, liquidated) - each on the whole margin."""
    equity = peak = 1.0
    drawdown = 0.0
    for move, liquidated in results:
        equity *= 0.0 if liquidated else max(0.0, 1 + move * leverage)
        peak = max(peak, equity)
        drawdown = min(drawdown, equity / peak - 1 if peak > 0 else -1.0)
    return (equity - 1) * 100, drawdown * 100


def run_exit_job(job: ExitJob) -> list[dict[str, object]]:
    """Every stop-loss x take-profit at the job's leverage."""
    index = {b.time: k for k, b in enumerate(job.bars)}
    rows: list[dict[str, object]] = []
    for stop_loss, take_profit in product(EXIT_STOP_LOSSES, EXIT_TAKE_PROFITS):
        trades = [
            t
            for t in with_paper_exits(job.trades, job.bars, stop_loss, take_profit)
            if t.opened_at >= job.start and t.exit_reason != OPEN_AT_END
        ]
        results: list[tuple[float, bool, SimTrade]] = []
        for t in trades:
            assert t.close_price is not None
            move = t.close_price / t.entry_price - 1
            net = (move if t.direction == "long" else -move) - 2 * job.fee_rate
            results.append((net, _liquidated(job, t, index), t))
        whole = _compound([(m, liq) for m, liq, _ in results], job.leverage)
        train = _compound([(m, q) for m, q, t in results if t.opened_at < job.split], job.leverage)
        test = _compound([(m, q) for m, q, t in results if t.opened_at >= job.split], job.leverage)
        rows.append(
            {
                "leverage": job.leverage,
                "stop_loss_pct": stop_loss,
                "take_profit_pct": take_profit,
                "return_pct": round(whole[0], 4),
                "max_drawdown_pct": round(whole[1], 4),
                "train_return_pct": round(train[0], 4),
                "test_return_pct": round(test[0], 4),
                "trades": len(results),
                "won": sum(m > 0 and not q for m, q, _ in results),
                "stops": sum(t.exit_reason == PAPER_STOP_LOSS for _, _, t in results),
                "take_profits": sum(t.exit_reason == PAPER_TAKE_PROFIT for _, _, t in results),
                "liquidations": sum(q for _, q, _ in results),
            }
        )
    return rows


@dataclass(frozen=True)
class ExitSweepPlan:
    start: datetime
    split: datetime
    end: datetime
    jobs: list[ExitJob]

    @property
    def runs(self) -> int:
        return len(self.jobs) * len(EXIT_STOP_LOSSES) * len(EXIT_TAKE_PROFITS)


async def plan_exit_sweep(paper: Paper, max_leverage: float | None = None) -> ExitSweepPlan:
    """The paper's sweep, ready to run: its strategy's trades (in a worker),
    one job per leverage up to `max_leverage` and the asset's max."""
    bars = await load_bars(paper)
    if len(bars) < 2:
        raise SweepError("no candles")
    end = bars[-1].time
    start = max(bars[0].time, end - timedelta(days=PAPER_DAYS))
    split = start + (end - start) * SPLIT
    loop = asyncio.get_running_loop()
    with _pool(max_workers=1) as pool:
        trades, _, _ = await loop.run_in_executor(
            pool,
            strategy_inputs,
            paper.executor,
            paper.asset,
            paper.direction,
            paper.timeframe,
            bars,
        )
    limits = await market_limits(paper.asset)
    top = min(
        limits.max_leverage if limits is not None else float("inf"),
        max_leverage if max_leverage is not None else float("inf"),
    )
    leverages = [float(x) for x in PAPER_LEVERAGES if x <= top]
    if not leverages:
        raise SweepError(f"no leverage of {PAPER_LEVERAGES} up to x{top:g}")
    maintenance = limits.maintenance_margin if limits is not None else None
    fee_rate = float(await maker_fee_rate())
    jobs = [
        ExitJob(bars, trades, leverage, maintenance, fee_rate, start, split)
        for leverage in leverages
    ]
    return ExitSweepPlan(start, split, end, jobs)


async def run_exit_sweep(
    plan: ExitSweepPlan, on_rows: Callable[[list[dict[str, object]]], Awaitable[None]]
) -> None:
    """A single paper's sweep: run_jobs over its leverages."""
    await run_jobs(plan.jobs, run_exit_job, on_rows)
