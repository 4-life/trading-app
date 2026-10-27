"""Temporary averaging parameter sweep (docs/papers.md#averaging-papers):
which averaging settings perform best, per asset and strategy. Nothing is
saved to the database but the candles - no papers, no backtest rows. Run
on the local server (it takes a while):

    python -m app.backtest.sweep <out.csv>

For every asset in ASSETS: a 1h Regime paper (not intraday) and a 15m VWAP
paper (intraday), long only, from the whole stored history. The
candles are backfilled first (the missing ranges over BACKFILL_DAYS, as the
backfill service does); the strategy's trades and signals are computed once
per asset and timeframe, then every combination of LEVERAGES x
ADD_LEVERAGES x TAKE_PROFITS replays them through the averaging backtest
(app/backtest/averaging.py) with the FIXED settings - one process per
asset and strategy.

Each paper is backtested alone with its own $MAX_MARGIN budget (live, two
papers can't hold one asset at once and the cash is shared - this is for
comparing them only). The history is split at SPLIT: the settings are
picked on the first part (train) and checked on the rest (test) - a
position counts in the part it opened in.

Writes one CSV row per run to <out.csv> and logs the
top TOP per asset and strategy, then the settings that do best over all
assets per strategy.

The API's POST /papers/{id}/sweep (plan_sweep, run_sweep, stored by
app/papers/sweeps.py): one averaging paper's settings instead - its executor,
timeframe, add leverage, add size (default: the initial size), max
drawdown and max margin fixed, every PAPER_LEVERAGES (up to the asset's max
leverage) x PAPER_INITIAL_SIZES x PAPER_TAKE_PROFITS x PAPER_MODES (hold,
intraday, intraday reopening in the trend) x compounding on / off (the
budget growing with the realized PnL - Rules.compound),
trading over the same period as the paper's backtest - from its
`backtest_start`, else its whole stored history (split at SPLIT, as
above); each run records when its cash fell under the initial size and it
stopped trading (drained_at) - a chunk per leverage x initial size, spread over the worker
processes - run at a low priority (WORKER_NICE): the API and the executors
come first.

Several papers' sweeps run one after another as a batch (app/papers/sweeps.py)."""

import asyncio
import csv
import logging
import os
import sys
import time
from collections import defaultdict
from collections.abc import Awaitable, Callable, Iterator, Sequence
from concurrent.futures import ProcessPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from itertools import product

from app.backtest.averaging import (
    ENTRY_SIGNALS,
    FILL_SLIPPAGE,
    LIQUIDATION_EXIT,
    STRATEGY_TRADES,
    AveragingTrade,
    Rules,
    rules_of,
    simulate,
)
from app.backtest.bars import Bar, SimTrade, load_bars
from app.backtest.models import OPEN_AT_END
from app.config import settings
from app.exchange.source import connected_adapter
from app.executors.position_management import MAX_DRAWDOWN_EXIT, OUT_OF_MARGIN_EXIT
from app.market_data.collector import backfill_candles
from app.market_data.limits import Limits, market_limits
from app.notifications.error_reporting import run_service
from app.papers.models import Paper
from app.system.exchange_api import maker_fee_rate

logger = logging.getLogger(__name__)

ASSETS = (
    "BTC", "ETH", "SOL", "BNB", "HYPE", "QQQ", "ZEC",
    "SOXL", "SNDK", "NVDA", "ENA", "XRP", "TRX", "SPY",
)  # fmt: skip
# (executor, timeframe, intraday)
STRATEGIES = (("regime", "1h", False), ("vwap", "15m", True))

LEVERAGES = (3, 5, 10, 20, 30, 50, 80, 100)
ADD_LEVERAGES = (1, 2, 3, 5)
TAKE_PROFITS = (0.01, 0.02, 0.05, 0.10, 0.20, 0.50)  # of the margin

INITIAL_SIZE = 10.0
ADD_SIZE = 20.0
MAX_DRAWDOWN = None  # the automatic give-up only, before the liquidation
MAX_MARGIN = 5000.0

# One paper's sweep (`paper <id>`).
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
TOP = 5


@dataclass(frozen=True)
class Job:
    asset: str
    executor: str
    timeframe: str
    intraday: bool
    bars: list[Bar]
    trades: list[SimTrade]
    signals: list[SimTrade]
    fee_rate: float
    limits: Limits | None  # the exchange's: leverages capped, its liquidation


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


def run(job: Job) -> list[dict[str, object]]:
    """Every combination of the settings over one asset and strategy."""
    t0 = time.monotonic()
    split = job.bars[0].time + (job.bars[-1].time - job.bars[0].time) * SPLIT
    rows: list[dict[str, object]] = []
    top = job.limits.max_leverage if job.limits else float("inf")
    for wanted, wanted_add, take_profit in product(LEVERAGES, ADD_LEVERAGES, TAKE_PROFITS):
        leverage, add_leverage = min(wanted, top), min(wanted_add, top)
        rules = Rules(
            leverage=leverage,
            initial_size=INITIAL_SIZE,
            add_leverage=add_leverage,
            add_size=ADD_SIZE,
            take_profit=take_profit,
            max_drawdown=MAX_DRAWDOWN,
            maintenance=settings.maintenance_margin_pct,
            max_margin=MAX_MARGIN,
            intraday=job.intraday,
            maintenance_notional=job.limits.maintenance_margin if job.limits else None,
            slippage=FILL_SLIPPAGE,
        )
        trades = simulate(job.bars, job.trades, rules, job.fee_rate, None, job.signals)
        rows.append(
            {
                "asset": job.asset,
                "executor": job.executor,
                "timeframe": job.timeframe,
                "intraday": job.intraday,
                "leverage": leverage,
                "add_leverage": add_leverage,
                "take_profit_pct": take_profit,
                "from": job.bars[0].time.date().isoformat(),
                "split": split.date().isoformat(),
                "to": job.bars[-1].time.date().isoformat(),
                "candles": len(job.bars),
                **_part(trades, "all"),
                **_part([t for t in trades if t.opened_at < split], "train"),
                **_part([t for t in trades if t.opened_at >= split], "test"),
            }
        )
    logger.info(
        "%s %s %s: %d runs over %d candles in %.0fs",
        job.asset,
        job.timeframe,
        job.executor,
        len(rows),
        len(job.bars),
        time.monotonic() - t0,
    )
    return rows


async def _backfill() -> None:
    """The missing candles of every asset and timeframe, over BACKFILL_DAYS."""
    _, adapter = await connected_adapter()
    end = datetime.now(UTC)
    start = end - timedelta(days=settings.backfill_days)
    start_ms, end_ms = int(start.timestamp() * 1000), int(end.timestamp() * 1000)
    for asset in ASSETS:
        if not adapter.is_listed(asset):
            logger.warning("%s: not listed by the provider - skipped", asset)
            continue
        for _, timeframe, _ in STRATEGIES:
            try:
                await backfill_candles(adapter, asset, timeframe, start_ms, end_ms)
            except Exception:
                logger.exception("%s %s: backfill failed - skipped", asset, timeframe)


async def _jobs() -> list[Job]:
    fee_rate = float(await maker_fee_rate())
    jobs: list[Job] = []
    for asset, (executor, timeframe, intraday) in product(ASSETS, STRATEGIES):
        paper = Paper(asset=asset, timeframe=timeframe, executor=executor, direction="long")
        bars = await load_bars(paper)
        if len(bars) < 2:
            logger.warning("%s %s: no candles - skipped", asset, timeframe)
            continue
        trades = STRATEGY_TRADES[executor](paper, bars, None)
        signals = ENTRY_SIGNALS[executor](paper, bars)
        limits = await market_limits(asset)
        jobs.append(
            Job(asset, executor, timeframe, intraday, bars, trades, signals, fee_rate, limits)
        )
    return jobs


def _settings(row: dict[str, object]) -> str:
    return f"x{row['leverage']} add x{row['add_leverage']} TP {row['take_profit_pct']:.0%}"


def _summary(rows: list[dict[str, object]]) -> None:
    """The best TOP per asset and strategy - picked on train (positive, no
    liquidation), ranked by test PnL - and per strategy, the settings with
    the most test PnL summed over every asset."""

    def num(row: dict[str, object], key: str) -> float:
        value = row[key]
        assert isinstance(value, int | float)
        return float(value)

    by_paper: dict[tuple[str, str], list[dict[str, object]]] = defaultdict(list)
    for row in rows:
        by_paper[(str(row["asset"]), str(row["executor"]))].append(row)
    for (asset, executor), runs in sorted(by_paper.items()):
        kept = [
            r for r in runs if num(r, "train_pnl_usd") > 0 and num(r, "train_liquidations") == 0
        ]
        kept.sort(key=lambda r: num(r, "test_pnl_usd"), reverse=True)
        logger.info("%s %s: %d of %d settings pass train", asset, executor, len(kept), len(runs))
        for r in kept[:TOP]:
            logger.info(
                "  %-24s train %+9.2f  test %+9.2f  all %+9.2f USD, most cash %8.2f, "
                "liquidations %d, give-ups %d, cash drawdown %+.2f",
                _settings(r),
                num(r, "train_pnl_usd"),
                num(r, "test_pnl_usd"),
                num(r, "all_pnl_usd"),
                num(r, "all_most_cash_usd"),
                int(num(r, "all_liquidations")),
                int(num(r, "all_give_ups")),
                num(r, "all_cash_drawdown_usd"),
            )
    for executor, _, _ in STRATEGIES:
        totals: dict[str, list[float]] = defaultdict(lambda: [0.0, 0.0, 0.0, 0.0])
        for r in rows:
            if r["executor"] != executor:
                continue
            t = totals[_settings(r)]
            t[0] += num(r, "test_pnl_usd")
            t[1] += num(r, "all_pnl_usd")
            t[2] += num(r, "test_pnl_usd") > 0
            t[3] += num(r, "all_liquidations")
        best = sorted(totals.items(), key=lambda kv: kv[1][0], reverse=True)[:TOP]
        logger.info("%s over all assets (by test PnL):", executor)
        for name, (test, all_, positive, liquidations) in best:
            logger.info(
                "  %-24s test %+10.2f  all %+10.2f USD, test positive on %d assets, "
                "%d liquidations",
                name,
                test,
                all_,
                int(positive),
                int(liquidations),
            )


def _write(rows: list[dict[str, object]], out: str) -> None:
    with open(out, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    logger.info("%d runs written to %s", len(rows), out)


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


async def main() -> None:
    if len(sys.argv) != 2:
        logger.warning("usage: python -m app.backtest.sweep <out.csv>")
        return
    out = sys.argv[1]
    await _backfill()
    jobs = await _jobs()
    runs = len(LEVERAGES) * len(ADD_LEVERAGES) * len(TAKE_PROFITS)
    logger.info("%d papers x %d settings: %d runs", len(jobs), runs, len(jobs) * runs)
    rows: list[dict[str, object]] = []
    with ProcessPoolExecutor() as pool:
        for result in pool.map(run, jobs):
            rows.extend(result)
    if not rows:
        logger.info("no candles - nothing to sweep")
        return
    _write(rows, out)
    _summary(rows)


if __name__ == "__main__":
    run_service("backtest", main)
