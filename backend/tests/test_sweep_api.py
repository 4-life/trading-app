"""Pure unit tests, no database."""

import asyncio
from collections.abc import Callable, Coroutine
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from app.backtest.models import PaperSweep
from app.backtest.sweep import SweepError, plan_sweep
from app.papers import sweeps
from app.papers.models import Paper


def _row() -> dict[str, object]:
    return {
        "leverage": 20.0,
        "add_leverage": 5.0,
        "initial_size": 100.0,
        "add_size": 100.0,
        "take_profit_pct": 0.2,
        "intraday": True,
        "total_usd": 100.0,
        "all_pnl_usd": 90.0,
        "all_open_unrealized_usd": 10.0,
        "train_pnl_usd": 70.0,
        "test_pnl_usd": 30.0,
        "all_positions": 12,
        "all_won": 10,
        "all_give_ups": 2,
        "all_liquidations": 0,
        "all_most_cash_usd": 900.0,
        "all_cash_drawdown_usd": -300.0,
    }


def test_a_compounding_run_is_stored_as_one() -> None:
    assert sweeps._run_row(7, _row()).compound is False
    assert sweeps._run_row(7, {**_row(), "compound": True}).compound is True


def test_a_runs_stats_are_stored_as_its_row() -> None:
    run = sweeps._run_row(7, _row())
    assert run.sweep_id == 7
    assert (run.leverage, run.initial_size_usd, run.take_profit_pct) == (
        Decimal(20),
        Decimal(100),
        Decimal("0.2"),
    )
    assert (run.total_usd, run.closed_pnl_usd, run.open_unrealized_usd) == (
        Decimal(100),
        Decimal(90),
        Decimal(10),
    )
    assert (run.positions, run.won, run.give_ups, run.liquidations) == (12, 10, 2, 0)
    assert run.most_margin_usd == Decimal(900) and run.intraday is True


def test_no_second_sweep_while_one_runs(monkeypatch: pytest.MonkeyPatch) -> None:
    running = PaperSweep(id=1, paper_id=195, status="running", started_at=datetime.now(UTC))

    async def busy() -> PaperSweep:
        return running

    monkeypatch.setattr(sweeps, "_close_interrupted", busy)
    paper = Paper(id=199, kind="averaging", executor="supertrend")
    with pytest.raises(sweeps.SweepBusy, match="paper 195"):
        asyncio.run(sweeps.start_sweep(paper, 20, 1000))


def test_only_an_averaging_paper_with_a_backtest_is_swept() -> None:
    with pytest.raises(SweepError, match="not an averaging or single paper"):
        asyncio.run(sweeps.start_sweep(Paper(kind="scanner", executor="trend"), 20, 1000))
    with pytest.raises(SweepError, match="has no backtest"):
        asyncio.run(plan_sweep(Paper(kind="averaging", executor="trend")))


def test_the_running_sweep_is_any_papers(monkeypatch: pytest.MonkeyPatch) -> None:
    running = PaperSweep(id=1, paper_id=195, status="running", started_at=datetime.now(UTC))

    async def busy() -> PaperSweep:
        return running

    monkeypatch.setattr(sweeps, "_close_interrupted", busy)
    assert asyncio.run(sweeps.running_sweep()) is running


def test_a_stopped_sweep_is_marked_stopped(monkeypatch: pytest.MonkeyPatch) -> None:
    finished: list[str] = []

    async def forever(*_: object) -> None:
        await asyncio.Event().wait()

    async def finish(_: int, status: str, error: str | None = None) -> None:
        finished.append(status)

    monkeypatch.setattr(sweeps, "plan_sweep", forever)
    monkeypatch.setattr(sweeps, "_finish", finish)

    async def stop() -> None:
        task = asyncio.create_task(sweeps._run(1, Paper(id=199), 20, 1000))
        await asyncio.sleep(0)
        task.cancel()
        await asyncio.wait([task])

    asyncio.run(stop())
    assert finished == ["stopped"]


def test_no_sweep_running_nothing_to_stop(monkeypatch: pytest.MonkeyPatch) -> None:
    async def none(_: int) -> None:
        return None

    monkeypatch.setattr(sweeps, "latest_sweep", none)
    with pytest.raises(sweeps.SweepNotRunning):
        asyncio.run(sweeps.stop_sweep(199))


def test_no_sweep_while_a_batch_runs(monkeypatch: pytest.MonkeyPatch) -> None:
    async def none() -> None:
        return None

    monkeypatch.setattr(sweeps, "_close_interrupted", none)

    async def start() -> None:
        batch = asyncio.create_task(asyncio.Event().wait())
        monkeypatch.setattr(sweeps, "_batch", (1, batch))
        try:
            paper = Paper(id=199, kind="averaging", executor="supertrend")
            with pytest.raises(sweeps.SweepBusy, match="batch"):
                await sweeps.start_sweep(paper, 20, 1000)
        finally:
            batch.cancel()

    asyncio.run(start())


def _batch_fakes(
    monkeypatch: pytest.MonkeyPatch, sweep_runs: Callable[[], Coroutine[None, None, None]]
) -> list[object]:
    """The batch's DB writes and each paper's sweep faked: the calls, in order."""
    calls: list[object] = []

    async def update(_: int, **values: object) -> None:
        calls.append(values.get("status", values.get("current_paper_id")))

    async def max_leverage(_: Paper) -> float:
        return 20.0

    async def create(paper: Paper, *_: object) -> PaperSweep:
        return PaperSweep(id=paper.id, paper_id=paper.id)

    def launch(sweep: PaperSweep, *_: object) -> asyncio.Task[None]:
        return asyncio.create_task(sweep_runs())

    monkeypatch.setattr(sweeps, "_update_batch", update)
    monkeypatch.setattr(sweeps, "_max_leverage", max_leverage)
    monkeypatch.setattr(sweeps, "_create", create)
    monkeypatch.setattr(sweeps, "_launch", launch)
    return calls


def test_a_batch_sweeps_its_papers_one_after_another(monkeypatch: pytest.MonkeyPatch) -> None:
    async def quick() -> None:
        await asyncio.sleep(0)

    calls = _batch_fakes(monkeypatch, quick)
    asyncio.run(sweeps._run_batch(1, [Paper(id=3), Paper(id=5)], 1000))
    assert calls == [3, 5, "done"]


def test_a_stopped_batch_stops_its_running_sweep(monkeypatch: pytest.MonkeyPatch) -> None:
    stopped: list[bool] = []

    async def forever() -> None:
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            stopped.append(True)
            raise

    calls = _batch_fakes(monkeypatch, forever)

    async def stop() -> None:
        task = asyncio.create_task(sweeps._run_batch(1, [Paper(id=3), Paper(id=5)], 1000))
        for _ in range(5):
            await asyncio.sleep(0)
        task.cancel()
        await asyncio.wait([task])

    asyncio.run(stop())
    assert stopped == [True]
    assert calls == [3, "stopped"]
