"""Averaging papers' settings sweeps, run in the API's background
(docs/papers.md#settings-sweep): each run's stats are stored as its chunk
finishes (`sweep_runs`), for the client to read sorted however it likes -
the sweep itself ranks nothing. One sweep at a time on the server; only a
paper's latest one is kept. A batch runs several averaging papers' sweeps
one after another, each on the same budget (`sweep_batches`, its latest
only) - no other sweep starts meanwhile."""

import asyncio
import logging
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any, Literal

from sqlalchemy import ColumnElement, asc, delete, desc, false, select, update

from app.backtest.exit_sweep import ExitSweepPlan, plan_exit_sweep, run_exit_sweep
from app.backtest.models import ExitSweepRun, PaperSweep, SweepBatch, SweepRun
from app.backtest.sweep import (
    PAPER_LEVERAGES,
    SweepError,
    check_sweepable,
    plan_sweep,
    run_sweep,
)
from app.db import async_session
from app.market_data.limits import market_limits
from app.papers.models import Paper

logger = logging.getLogger(__name__)

# The stats the runs can be sorted by (SweepRun's columns).
# Not stats - rankings of their own (sweep_runs), `order` aside: the fewest
# give-ups (liquidations counted in) / the most winning positions, each with
# the best total among them.
SAFEST_TOTAL = "safest_total"
MOST_WON_TOTAL = "most_won_total"
SweepSort = Literal[
    "safest_total",
    "most_won_total",
    "total_usd",
    "closed_pnl_usd",
    "open_unrealized_usd",
    "train_pnl_usd",
    "test_pnl_usd",
    "positions",
    "won",
    "give_ups",
    "liquidations",
    "most_margin_usd",
    "cash_drawdown_usd",
    "leverage",
    "initial_size_usd",
    "take_profit_pct",
]
INTERRUPTED = "interrupted - the API restarted while it ran"
# A run is tight when its most margin locked at once left less than this
# share of the sweep's max margin unused: live slippage and fees beyond the
# backtest's would have liquidated it.
MIN_HEADROOM = Decimal("0.2")

# The sweeps running in this process (one uvicorn process); a sweep stored as
# running but not here was cut off by a restart.
_running: set[int] = set()
_tasks: dict[int, asyncio.Task[None]] = {}  # by sweep id
# The batch running in this process: its id and task; a batch stored as
# running but not here was cut off by a restart.
_batch: tuple[int, asyncio.Task[None]] | None = None


class SweepNotRunning(Exception):
    """The paper has no sweep running - nothing to stop."""


class SweepBusy(Exception):
    """Another sweep (or a batch) is running - only one at a time."""


def _busy(sweep: PaperSweep) -> SweepBusy:
    return SweepBusy(f"a sweep is running (paper {sweep.paper_id}) - wait for it to finish")


def _batch_running() -> bool:
    return _batch is not None and not _batch[1].done()


async def _close_interrupted() -> PaperSweep | None:
    """Marks the sweeps and batches stored as running but not running here
    as failed; the sweep running here, if any."""
    now = datetime.now(UTC)
    async with async_session() as session, session.begin():
        rows = (
            await session.scalars(select(PaperSweep).where(PaperSweep.status == "running"))
        ).all()
        running = None
        for row in rows:
            if row.id in _running:
                running = row
            else:
                row.status, row.error, row.finished_at = "failed", INTERRUPTED, now
        batches = (
            await session.scalars(select(SweepBatch).where(SweepBatch.status == "running"))
        ).all()
        for batch in batches:
            if not (_batch_running() and _batch is not None and _batch[0] == batch.id):
                batch.status, batch.error, batch.finished_at = "failed", INTERRUPTED, now
    return running


def _date(value: object) -> date | None:
    return None if value is None else date.fromisoformat(str(value))


def _run_row(sweep_id: int, r: dict[str, object]) -> SweepRun:
    def num(key: str) -> Decimal:
        return Decimal(str(r[key]))

    return SweepRun(
        sweep_id=sweep_id,
        leverage=num("leverage"),
        add_leverage=num("add_leverage"),
        initial_size_usd=num("initial_size"),
        add_size_usd=num("add_size"),
        take_profit_pct=num("take_profit_pct"),
        intraday=bool(r["intraday"]),
        reopen=bool(r.get("reopen", False)),
        compound=bool(r.get("compound", False)),
        total_usd=num("total_usd"),
        closed_pnl_usd=num("all_pnl_usd"),
        open_unrealized_usd=num("all_open_unrealized_usd"),
        train_pnl_usd=num("train_pnl_usd"),
        test_pnl_usd=num("test_pnl_usd"),
        positions=int(num("all_positions")),
        won=int(num("all_won")),
        give_ups=int(num("all_give_ups")),
        liquidations=int(num("all_liquidations")),
        most_margin_usd=num("all_most_cash_usd"),
        cash_drawdown_usd=num("all_cash_drawdown_usd"),
        drained_at=_date(r.get("drained_at")),
    )


# The stats a single paper's sweep runs can be sorted by (ExitSweepRun's columns).
ExitSweepSort = Literal[
    "return_pct",
    "test_return_pct",
    "train_return_pct",
    "max_drawdown_pct",
    "trades",
    "won",
    "stops",
    "take_profits",
    "liquidations",
    "leverage",
    "stop_loss_pct",
    "take_profit_pct",
]


def _exit_run_row(sweep_id: int, r: dict[str, object]) -> ExitSweepRun:
    def num(key: str) -> Decimal | None:
        value = r[key]
        return None if value is None else Decimal(str(value))

    def count(key: str) -> int:
        return int(str(r[key]))

    return ExitSweepRun(
        sweep_id=sweep_id,
        leverage=num("leverage"),
        stop_loss_pct=num("stop_loss_pct"),
        take_profit_pct=num("take_profit_pct"),
        return_pct=num("return_pct"),
        max_drawdown_pct=num("max_drawdown_pct"),
        train_return_pct=num("train_return_pct"),
        test_return_pct=num("test_return_pct"),
        trades=count("trades"),
        won=count("won"),
        stops=count("stops"),
        take_profits=count("take_profits"),
        liquidations=count("liquidations"),
    )


async def _finish(sweep_id: int, status: str, error: str | None = None) -> None:
    async with async_session() as session, session.begin():
        await session.execute(
            update(PaperSweep)
            .where(PaperSweep.id == sweep_id)
            .values(status=status, error=error, finished_at=datetime.now(UTC))
        )


async def _run(sweep_id: int, paper: Paper, max_leverage: float, max_margin: float | None) -> None:
    try:
        # A single paper: its leverage, stop-loss and take-profit; else averaging.
        single = paper.kind == "single"
        plan = (
            await plan_exit_sweep(paper, max_leverage)
            if single
            else await plan_sweep(paper, max_leverage, max_margin)
        )
        async with async_session() as session, session.begin():
            await session.execute(
                update(PaperSweep)
                .where(PaperSweep.id == sweep_id)
                .values(
                    start=plan.start.date(),
                    split=plan.split.date(),
                    end=plan.end.date(),
                    runs_total=plan.runs,
                )
            )

        async def save(rows: list[dict[str, object]]) -> None:
            async with async_session() as session, session.begin():
                row_of = _exit_run_row if single else _run_row
                session.add_all(row_of(sweep_id, r) for r in rows)
                await session.execute(
                    update(PaperSweep)
                    .where(PaperSweep.id == sweep_id)
                    .values(runs_done=PaperSweep.runs_done + len(rows))
                )

        if isinstance(plan, ExitSweepPlan):
            await run_exit_sweep(plan, save)
        else:
            await run_sweep(plan, save)
        await _finish(sweep_id, "done")
    except asyncio.CancelledError:
        # Stopped: the runs stored so far are kept.
        await _finish(sweep_id, "stopped")
        raise
    except SweepError as exc:
        await _finish(sweep_id, "failed", str(exc))
    except Exception as exc:
        logger.exception("paper %d: the sweep failed", paper.id)
        await _finish(sweep_id, "failed", f"the sweep failed: {exc}")
    finally:
        _running.discard(sweep_id)


def _check(paper: Paper, max_margin: float | None) -> None:
    check_sweepable(paper)
    if paper.kind != "single" and max_margin is None:
        raise SweepError("an averaging paper's sweep needs a max margin")


async def _create(paper: Paper, max_leverage: float, max_margin: float | None) -> PaperSweep:
    """The paper's new sweep, stored as running - its previous one deleted."""
    async with async_session() as session, session.begin():
        # Its runs go with it (ON DELETE CASCADE).
        await session.execute(delete(PaperSweep).where(PaperSweep.paper_id == paper.id))
        sweep = PaperSweep(
            paper_id=paper.id,
            status="running",
            max_leverage=Decimal(str(max_leverage)),
            max_margin=None if max_margin is None else Decimal(str(max_margin)),
            runs_total=0,
            runs_done=0,
            started_at=datetime.now(UTC),
        )
        session.add(sweep)
        await session.flush()
    return sweep


def _launch(
    sweep: PaperSweep, paper: Paper, max_leverage: float, max_margin: float | None
) -> asyncio.Task[None]:
    _running.add(sweep.id)
    task = asyncio.create_task(_run(sweep.id, paper, max_leverage, max_margin))
    _tasks[sweep.id] = task
    task.add_done_callback(lambda _: _tasks.pop(sweep.id, None))
    return task


async def start_sweep(paper: Paper, max_leverage: float, max_margin: float | None) -> PaperSweep:
    """Starts the paper's sweep in the background, replacing its previous
    one: an averaging paper's (its budget `max_margin`, required) or a
    single paper's (its leverage, stop-loss and take-profit). SweepError for
    a paper it can't run on, SweepBusy while another (or a batch) runs."""
    _check(paper, max_margin)
    busy = await _close_interrupted()
    if busy is not None:
        raise _busy(busy)
    if _batch_running():
        raise SweepBusy("a batch sweep is running - wait for it to finish or stop it")
    sweep = await _create(paper, max_leverage, max_margin)
    _launch(sweep, paper, max_leverage, max_margin)
    return sweep


async def _max_leverage(paper: Paper) -> float:
    """The highest leverage a batch tries on the paper: the asset's max."""
    limits = await market_limits(paper.asset)
    return limits.max_leverage if limits is not None else float(max(PAPER_LEVERAGES))


async def _update_batch(batch_id: int, **values: object) -> None:
    async with async_session() as session, session.begin():
        await session.execute(update(SweepBatch).where(SweepBatch.id == batch_id).values(**values))


async def _run_batch(batch_id: int, papers: list[Paper], max_margin: float) -> None:
    current: asyncio.Task[None] | None = None
    try:
        for done, paper in enumerate(papers):
            await _update_batch(batch_id, current_paper_id=paper.id, papers_done=done)
            max_leverage = await _max_leverage(paper)
            sweep = await _create(paper, max_leverage, max_margin)
            current = _launch(sweep, paper, max_leverage, max_margin)
            # Its own stop (the paper's Stop) ends it alone: on to the next.
            await asyncio.wait([current])
        await _update_batch(
            batch_id,
            status="done",
            current_paper_id=None,
            papers_done=len(papers),
            finished_at=datetime.now(UTC),
        )
    except asyncio.CancelledError:
        # Stopped: the running paper's sweep too, its runs so far kept.
        if current is not None and not current.done():
            current.cancel()
            await asyncio.wait([current])
        await _update_batch(batch_id, status="stopped", finished_at=datetime.now(UTC))
        raise
    except Exception as exc:
        logger.exception("batch %d failed", batch_id)
        await _update_batch(
            batch_id,
            status="failed",
            error=f"the batch failed: {exc}",
            finished_at=datetime.now(UTC),
        )


async def start_batch(paper_ids: list[int], max_margin: float) -> SweepBatch:
    """Starts the papers' sweeps (averaging ones) in the background, one
    after another in the given order, each on the `max_margin` budget and
    up to its asset's max leverage - replacing their previous sweeps and the
    previous batch. SweepError for a paper it can't run on, SweepBusy while
    a sweep or a batch runs."""
    global _batch
    ids = list(dict.fromkeys(paper_ids))
    if not ids:
        raise SweepError("no papers picked")
    async with async_session() as session:
        found = {p.id: p for p in (await session.scalars(select(Paper).where(Paper.id.in_(ids))))}
    missing = [str(i) for i in ids if i not in found]
    if missing:
        raise SweepError(f"no paper {', '.join(missing)}")
    for paper in found.values():
        if paper.kind != "averaging":
            raise SweepError(f"paper {paper.id} isn't an averaging paper")
        _check(paper, max_margin)
    busy = await _close_interrupted()
    if busy is not None:
        raise _busy(busy)
    if _batch_running():
        raise SweepBusy("a batch sweep is running - wait for it to finish or stop it")
    async with async_session() as session, session.begin():
        await session.execute(delete(SweepBatch))
        batch = SweepBatch(
            status="running",
            max_margin=Decimal(str(max_margin)),
            paper_ids=ids,
            papers_done=0,
            started_at=datetime.now(UTC),
        )
        session.add(batch)
        await session.flush()
    task = asyncio.create_task(_run_batch(batch.id, [found[i] for i in ids], max_margin))
    _batch = (batch.id, task)
    return batch


async def latest_batch() -> SweepBatch | None:
    """The latest batch, an interrupted one marked failed first."""
    await _close_interrupted()
    async with async_session() as session:
        batch: SweepBatch | None = await session.scalar(
            select(SweepBatch).order_by(SweepBatch.started_at.desc()).limit(1)
        )
    return batch


async def stop_batch() -> SweepBatch:
    """Stops the running batch - its running paper's sweep too, the runs
    stored so far kept; the batch, stopped. SweepNotRunning without one."""
    if _batch is None or not _batch_running():
        raise SweepNotRunning("no batch sweep running")
    task = _batch[1]
    task.cancel()
    await asyncio.wait([task])
    stopped = await latest_batch()
    assert stopped is not None
    return stopped


async def stop_sweep(paper_id: int) -> PaperSweep:
    """Stops the paper's running sweep, keeping the runs stored so far; the
    sweep, stopped. SweepNotRunning when it has none running."""
    sweep = await latest_sweep(paper_id)
    task = _tasks.get(sweep.id) if sweep is not None else None
    if sweep is None or task is None:
        raise SweepNotRunning("no sweep running for this paper")
    task.cancel()
    await asyncio.wait([task])
    stopped = await latest_sweep(paper_id)
    assert stopped is not None
    return stopped


async def running_sweep() -> PaperSweep | None:
    """The sweep running on the server (one at a time), interrupted ones
    marked failed first."""
    return await _close_interrupted()


async def latest_sweep(paper_id: int) -> PaperSweep | None:
    """The paper's sweep (its latest), interrupted ones marked failed first."""
    await _close_interrupted()
    async with async_session() as session:
        sweep: PaperSweep | None = await session.scalar(
            select(PaperSweep)
            .where(PaperSweep.paper_id == paper_id)
            .order_by(PaperSweep.started_at.desc())
            .limit(1)
        )
    return sweep


async def sweep_runs(
    sweep_id: int,
    sort: SweepSort,
    order: Literal["asc", "desc"],
    limit: int,
    compound: bool = False,
    max_margin: Decimal | None = None,
    robust_only: bool = False,
) -> list[SweepRun]:
    """The sweep's runs so far with compounding on / off, sorted by `sort`
    (SAFEST_TOTAL, MOST_WON_TOTAL: their own order, `order` aside) - the
    drained ones (stopped trading, out of cash) last, then the tight ones
    (under MIN_HEADROOM of the sweep's `max_margin` left, fixed budget
    only); `robust_only`: neither."""
    rankings: dict[str, list[ColumnElement[Any]]] = {
        SAFEST_TOTAL: [
            (SweepRun.give_ups + SweepRun.liquidations).asc(),
            SweepRun.total_usd.desc(),
        ],
        MOST_WON_TOTAL: [SweepRun.won.desc(), SweepRun.total_usd.desc()],
    }
    ordering = rankings.get(sort) or [(desc if order == "desc" else asc)(getattr(SweepRun, sort))]
    drained = SweepRun.drained_at.is_not(None)
    # Compounding, a position's budget is the cash, past the max margin: no cap to measure.
    tight = (
        false()
        if max_margin is None or compound
        else SweepRun.most_margin_usd > max_margin * (1 - MIN_HEADROOM)
    )
    query = select(SweepRun).where(SweepRun.sweep_id == sweep_id, SweepRun.compound == compound)
    if robust_only:
        query = query.where(~drained, ~tight)
    async with async_session() as session:
        rows = await session.scalars(
            query.order_by(drained.asc(), tight.asc(), *ordering, SweepRun.id).limit(limit)
        )
        return list(rows.all())


async def exit_sweep_runs(
    sweep_id: int, sort: ExitSweepSort, order: Literal["asc", "desc"], limit: int
) -> list[ExitSweepRun]:
    """A single paper's sweep runs so far, sorted by `sort` - none (a null
    stop-loss / take-profit) last."""
    column = getattr(ExitSweepRun, sort)
    ordered = column.desc().nulls_last() if order == "desc" else column.asc().nulls_last()
    async with async_session() as session:
        rows = await session.scalars(
            select(ExitSweepRun)
            .where(ExitSweepRun.sweep_id == sweep_id)
            .order_by(ordered, ExitSweepRun.id)
            .limit(limit)
        )
        return list(rows.all())
