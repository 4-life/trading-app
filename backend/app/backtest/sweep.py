"""An averaging paper's settings sweep (docs/papers.md#averaging-papers), the
API's POST /papers/{id}/sweep (plan_sweep, run_sweep, stored by
app/papers/sweeps.py): its executor, timeframe, add leverage, add size
(default: the initial size), max drawdown and max margin fixed, every
PAPER_LEVERAGES (up to the asset's max leverage) x PAPER_INITIAL_SIZES x
PAPER_TAKE_PROFITS x PAPER_MODES (hold, intraday, intraday reopening in the
trend) x compounding on / off (the budget growing with the realized PnL -
Rules.compound), trading over the same period as the paper's backtest -
from its `backtest_start`, else its whole stored history, split at SPLIT:
train before, test after (a position counts in the part it opened in);
each run records when its cash fell under the initial size and it stopped
trading (drained_at) - a chunk per leverage x initial size, spread over the
worker processes - run at a low priority (WORKER_NICE): the API and the
executors come first. Nothing is saved but the runs' stats.

Several papers' sweeps run one after another as a batch (app/papers/sweeps.py)."""

import asyncio
import logging
import os
from collections.abc import Awaitable, Callable, Iterator, Sequence
from concurrent.futures import ProcessPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import datetime
from itertools import product

from app.backtest.averaging import (
    ENTRY_SIGNALS,
    LIQUIDATION_EXIT,
    STRATEGY_TRADES,
    AveragingTrade,
    Rules,
    rules_of,
    simulate,
)
from app.backtest.bars import Bar, SimTrade, load_bars
from app.backtest.models import OPEN_AT_END
from app.executors.position_management import MAX_DRAWDOWN_EXIT, OUT_OF_MARGIN_EXIT
from app.market_data.limits import market_limits
from app.papers.models import Paper
from app.system.exchange_api import maker_fee_rate

logger = logging.getLogger(__name__)

PAPER_LEVERAGES = (3, 5, 10, 15, 20, 30, 50, 75, 100)  # those over the asset's max left out
PAPER_INITIAL_SIZES = (
    10.0, 15.0, 20.0, 30.0, 40.0, 50.0, 60.0, 70.0, 80.0, 90.0, 100.0, 120.0, 150.0, 200.0, 250.0,
    300.0, 400.0, 500.0, 600.0, 700.0,
)  # fmt: skip
PAPER_TAKE_PROFITS = (
    0.01, 0.02, 0.03, 0.05, 0.075, 0.10, 0.15, 0.20,
    0.25, 0.30, 0.40, 0.50, 0.75, 1.00, 1.50, 2.00,
)  # of the margin  # fmt: skip
PAPER_DAYS = 365  # a single paper's sweep (app/backtest/exit_sweep.py)
# (intraday, reopen): hold for the strategy's sell, intraday, intraday reopening
# after a take-profit while the trend lasts (Rules.reopen).
PAPER_MODES = ((False, False), (True, False), (True, True))

SPLIT = 0.7  # the train share of the history
WORKER_NICE = 10  # the sweep workers' CPU priority: below the API's and the executors'


def _part(trades: list[AveragingTrade], prefix: str) -> dict[str, float]:
    """One part's results: its closed positions and the one still open at
    the end. `cash_drawdown`: the deepest drop of the summed PnL from its
    peak, in USD - how far the budget fell."""
    closed = [t for t in trades if t.exit_reason != OPEN_AT_END]
    open_ = [t for t in trades if t.exit_reason == OPEN_AT_END]
    pnl = peak = worst = 0.0
    for t in closed:
        pnl += t.pnl_usd
        peak = max(peak, pnl)
        worst = min(worst, pnl - peak)
    most_cash = max((t.margin for t in trades), default=0.0)
    return {
        f"{prefix}_positions": len(closed),
        f"{prefix}_won": sum(t.pnl_usd > 0 for t in closed),
        f"{prefix}_liquidations": sum(t.exit_reason == LIQUIDATION_EXIT for t in closed),
        f"{prefix}_give_ups": sum(
            t.exit_reason in (MAX_DRAWDOWN_EXIT, OUT_OF_MARGIN_EXIT) for t in closed
        ),
        f"{prefix}_pnl_usd": round(pnl, 2),
        f"{prefix}_most_cash_usd": round(most_cash, 2),
        f"{prefix}_return_on_cash_pct": round(pnl / most_cash * 100, 2) if most_cash else 0.0,
        f"{prefix}_cash_drawdown_usd": round(worst, 2),
        f"{prefix}_adds": sum(t.adds for t in closed),
        f"{prefix}_open_unrealized_usd": round(sum(t.pnl_usd for t in open_), 2),
        f"{prefix}_open_margin_usd": round(sum(t.margin for t in open_), 2),
    }


@dataclass(frozen=True)
class PaperJob:
    """One leverage x initial size of a paper's sweep - a worker process's
    chunk: every take-profit x mode."""

    paper: int
    asset: str
    executor: str
    timeframe: str
    add_size: float | None  # the paper's; None: the initial size
    bars: list[Bar]
    trades: list[SimTrade]
    signals: list[SimTrade]
    rules: Rules  # the paper's, at this leverage
    fee_rate: float
    start: datetime
    split: datetime
    initial_size: float


def run_paper(job: PaperJob) -> list[dict[str, object]]:
    """Every take-profit x mode x compounding at the job's leverage and
    initial size."""
    rows: list[dict[str, object]] = []
    end = job.bars[-1].time
    initial = job.initial_size
    for take_profit, (intraday, reopen), compound in product(
        PAPER_TAKE_PROFITS, PAPER_MODES, (False, True)
    ):
        add = job.add_size if job.add_size is not None else initial
        rules = replace(
            job.rules,
            initial_size=initial,
            add_size=add,
            take_profit=take_profit,
            intraday=intraday,
            reopen=reopen,
            compound=compound,
        )
        result = simulate(job.bars, job.trades, rules, job.fee_rate, job.start, job.signals)
        whole = _part(result, "all")
        drained = drained_at(result, rules)
        rows.append(
            {
                "paper": job.paper,
                "asset": job.asset,
                "executor": job.executor,
                "timeframe": job.timeframe,
                "leverage": rules.leverage,
                "add_leverage": rules.add_leverage,
                "add_size": add,
                "max_margin": rules.max_margin,
                "initial_size": initial,
                "take_profit_pct": take_profit,
                "intraday": intraday,
                "reopen": reopen,
                "compound": compound,
                "from": job.start.date().isoformat(),
                "split": job.split.date().isoformat(),
                "to": end.date().isoformat(),
                "total_usd": round(whole["all_pnl_usd"] + whole["all_open_unrealized_usd"], 2),
                "drained_at": None if drained is None else drained.date().isoformat(),
                **whole,
                **_part([t for t in result if t.opened_at < job.split], "train"),
                **_part([t for t in result if t.opened_at >= job.split], "test"),
            }
        )
    return rows


def drained_at(trades: list[AveragingTrade], rules: Rules) -> datetime | None:
    """When the cash (simulate's budget: the max margin plus every closed
    position's PnL) fell under the initial size - no position opens after
    it; None if it never did (or without a max margin)."""
    if rules.max_margin is None:
        return None
    cash = rules.max_margin
    for t in trades:
        if t.exit_reason == OPEN_AT_END:
            continue
        cash += t.pnl_usd
        if cash < rules.initial_size:
            return t.closed_at
    return None


class SweepError(Exception):
    """A paper the sweep can't run on - the reason."""


def strategy_inputs(
    executor: str,
    asset: str,
    direction: str,
    timeframe: str,
    bars: list[Bar],
    start: datetime | None = None,
) -> tuple[list[SimTrade], list[SimTrade]]:
    """The strategy's trades from `start` and its long signals over `bars` -
    in a worker process (sweep_paper)."""
    paper = Paper(executor=executor, asset=asset, direction=direction, timeframe=timeframe)
    return STRATEGY_TRADES[executor](paper, bars, start), ENTRY_SIGNALS[executor](paper, bars)


def check_sweepable(paper: Paper) -> None:
    """Raises SweepError for a paper no sweep can run on - an averaging
    paper's sweep (here) or a single paper's (app/backtest/exit_sweep.py)."""
    if paper.kind not in ("averaging", "single"):
        raise SweepError("not an averaging or single paper")
    if paper.executor not in STRATEGY_TRADES or paper.executor not in ENTRY_SIGNALS:
        raise SweepError(f"{paper.executor} has no backtest")


@dataclass(frozen=True)
class SweepPlan:
    """A paper's sweep, ready to run: its period and its chunks."""

    start: datetime
    split: datetime
    end: datetime
    leverages: list[float]
    jobs: list[PaperJob]

    @property
    def runs(self) -> int:
        return len(self.jobs) * len(PAPER_TAKE_PROFITS) * len(PAPER_MODES) * 2  # x compound


async def plan_sweep(
    paper: Paper, max_leverage: float | None = None, max_margin: float | None = None
) -> SweepPlan:
    """One averaging paper's sweep (see the module doc): every leverage up to
    `max_leverage` (also capped at the asset's max), `max_margin` as the
    budget instead of the paper's - one chunk per leverage x initial size."""
    check_sweepable(paper)
    if paper.kind != "averaging":
        raise SweepError("not an averaging paper")
    bars = await load_bars(paper)
    if len(bars) < 2:
        raise SweepError("no candles")
    end = bars[-1].time
    # The paper's backtest period (app/backtest/averaging.py backtest_paper):
    # its results compare with the sweep's.
    start = max(bars[0].time, paper.backtest_start or bars[0].time)
    if start >= end:
        raise SweepError("the backtest start is after the last candle")
    split = start + (end - start) * SPLIT
    # The strategy's trades in a worker process too - CPU-heavy, and the API
    # runs this: its other requests mustn't wait.
    loop = asyncio.get_running_loop()
    with _pool(max_workers=1) as pool:
        trades, signals = await loop.run_in_executor(
            pool,
            strategy_inputs,
            paper.executor,
            paper.asset,
            paper.direction,
            paper.timeframe,
            bars,
            paper.backtest_start,
        )
    fee_rate = float(await maker_fee_rate())
    limits = await market_limits(paper.asset)
    base = rules_of(paper, limits)
    if max_margin is not None:
        base = replace(base, max_margin=max_margin)
    top = min(
        limits.max_leverage if limits is not None else float("inf"),
        max_leverage if max_leverage is not None else float("inf"),
    )
    leverages = [float(x) for x in PAPER_LEVERAGES if x <= top]
    if not leverages:
        raise SweepError(f"no leverage of {PAPER_LEVERAGES} up to x{top:g}")
    add_size = float(paper.add_size_usd) if paper.add_size_usd is not None else None
    jobs = [
        PaperJob(
            paper.id,
            paper.asset,
            paper.executor,
            paper.timeframe,
            add_size,
            bars,
            trades,
            signals,
            replace(base, leverage=leverage),
            fee_rate,
            start,
            split,
            initial,
        )
        for leverage, initial in product(leverages, PAPER_INITIAL_SIZES)
    ]
    plan = SweepPlan(start, split, end, leverages, jobs)
    logger.info(
        "paper %d: leverages %s, add x%g, max $%s, %s -> %s: %d runs",
        paper.id,
        ", ".join(f"x{x:g}" for x in leverages),
        base.add_leverage,
        base.max_margin,
        start.date(),
        end.date(),
        plan.runs,
    )
    return plan


@contextmanager
def _pool(max_workers: int | None = None) -> Iterator[ProcessPoolExecutor]:
    """A process pool whose workers are killed when the sweep is stopped
    (cancelled) or fails - instead of waiting for their chunks. Its workers
    run at WORKER_NICE."""
    pool = ProcessPoolExecutor(max_workers, initializer=os.nice, initargs=(WORKER_NICE,))
    try:
        yield pool
    except BaseException:
        pool.kill_workers()
        raise
    pool.shutdown()


async def run_jobs[J](
    jobs: Sequence[J],
    work: Callable[[J], list[dict[str, object]]],
    on_rows: Callable[[list[dict[str, object]]], Awaitable[None]],
) -> None:
    """Runs `work` on every job in worker processes, handing each one's rows
    to `on_rows` as it finishes - no ranking, the stats only."""
    loop = asyncio.get_running_loop()
    with _pool() as pool:
        futures = [loop.run_in_executor(pool, work, j) for j in jobs]
        for future in asyncio.as_completed(futures):
            await on_rows(await future)


async def run_sweep(
    plan: SweepPlan, on_rows: Callable[[list[dict[str, object]]], Awaitable[None]]
) -> None:
    """An averaging paper's sweep: run_jobs over its chunks."""
    await run_jobs(plan.jobs, run_paper, on_rows)
