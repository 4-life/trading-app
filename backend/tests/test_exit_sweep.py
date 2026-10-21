"""Pure unit tests, no database."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.backtest.bars import Bar, SimTrade
from app.backtest.exit_sweep import (
    EXIT_STOP_LOSSES,
    EXIT_TAKE_PROFITS,
    ExitJob,
    _compound,
    liquidation_price,
    run_exit_job,
)
from app.papers.sweeps import _exit_run_row

T0 = datetime(2026, 10, 1, tzinfo=UTC)


def test_the_liquidation_price_at_a_leverage() -> None:
    # x50 with 1.2% maintenance: the equity at 1.2% of the notional at ~99.19.
    assert liquidation_price("long", 100, 50, 0.012) == pytest.approx(98 / 0.988)
    assert liquidation_price("short", 100, 50, 0.012) == pytest.approx(102 / 1.012)
    # Without the exchange's: the margin left down to 20% of it (2% at x10 -> -8%).
    assert liquidation_price("long", 100, 10, None) == pytest.approx(92)


def test_compounding_each_trade_on_the_whole_margin() -> None:
    # +1% and -1% of price at x10: x1.1 then x0.9 = -1%; drawdown -10%.
    total, drawdown = _compound([(0.01, False), (-0.01, False)], 10)
    assert total == pytest.approx(-1)
    assert drawdown == pytest.approx(-10)
    # A liquidation takes the equity.
    total, drawdown = _compound([(0.05, False), (0.0, True)], 10)
    assert (total, drawdown) == (-100.0, -100.0)


def _bars(*candles: tuple[float, float, float, float]) -> list[Bar]:
    return [Bar(T0 + timedelta(hours=k), *c) for k, c in enumerate(candles)]


def test_every_stop_loss_and_take_profit_at_the_jobs_leverage() -> None:
    bars = _bars(
        (100, 100, 100, 100),  # entry
        (100, 101, 98.5, 100),  # -1.5%: a 1% stop is hit; liquidation at x50 (~-0.8%) too
        (100, 103, 100, 102),  # the strategy's exit at 102
    )
    trade = SimTrade("long", T0, 100.0, None, entry_reason="x")
    trade.closed_at, trade.close_price, trade.exit_reason = T0 + timedelta(hours=2), 102.0, "sig"
    job = ExitJob(bars, [trade], 10, 0.012, 0.0, T0, T0 + timedelta(hours=1))
    rows = run_exit_job(job)
    assert len(rows) == len(EXIT_STOP_LOSSES) * len(EXIT_TAKE_PROFITS)
    plain = next(r for r in rows if r["stop_loss_pct"] is None and r["take_profit_pct"] is None)
    assert plain["return_pct"] == pytest.approx(20)  # +2% at x10
    assert (plain["trades"], plain["won"], plain["liquidations"]) == (1, 1, 0)
    stopped = next(r for r in rows if r["stop_loss_pct"] == 0.01 and r["take_profit_pct"] is None)
    assert stopped["stops"] == 1 and float(str(stopped["return_pct"])) < 0
    # x50: the 1.5% dip passes the liquidation (~0.8%) with no stop tighter than it.
    at_50 = run_exit_job(ExitJob(bars, [trade], 50, 0.012, 0.0, T0, T0 + timedelta(hours=1)))
    plain_50 = next(r for r in at_50 if r["stop_loss_pct"] is None and r["take_profit_pct"] is None)
    assert plain_50["liquidations"] == 1 and plain_50["return_pct"] == pytest.approx(-100)
    tight_50 = next(
        r for r in at_50 if r["stop_loss_pct"] == 0.005 and r["take_profit_pct"] is None
    )
    assert tight_50["liquidations"] == 0 and tight_50["stops"] == 1


def test_a_runs_stats_are_stored_as_its_row() -> None:
    row: dict[str, object] = {
        "leverage": 10.0,
        "stop_loss_pct": None,
        "take_profit_pct": 0.05,
        "return_pct": 12.5,
        "max_drawdown_pct": -4.0,
        "train_return_pct": 10.0,
        "test_return_pct": 2.3,
        "trades": 8,
        "won": 5,
        "stops": 0,
        "take_profits": 3,
        "liquidations": 0,
    }
    run = _exit_run_row(4, row)
    assert (run.sweep_id, run.stop_loss_pct, run.take_profit_pct) == (4, None, Decimal("0.05"))
    assert (run.return_pct, run.trades, run.take_profits) == (Decimal("12.5"), 8, 3)
