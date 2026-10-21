"""Pure unit tests, no database."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.backtest.bars import STOP_SLIPPAGE, Bar, SimTrade, with_paper_exits
from app.executors.paper_exits import (
    PAPER_STOP_LOSS,
    PAPER_TAKE_PROFIT,
    levels,
    paper_exit,
    with_paper_levels,
)
from app.order_queue import Signal
from app.papers.models import Paper

T0 = datetime(2026, 10, 1, tzinfo=UTC)


def _paper(sl: str | None, tp: str | None) -> Paper:
    return Paper(
        stop_loss_pct=None if sl is None else Decimal(sl),
        price_take_profit_pct=None if tp is None else Decimal(tp),
    )


def test_a_long_and_a_short_close_at_the_papers_stop_or_take_profit() -> None:
    paper = _paper("0.02", "0.05")
    assert levels(paper, "long", Decimal(100)) == (Decimal(98), Decimal(105))
    assert levels(paper, "short", Decimal(100)) == (Decimal(102), Decimal(95))
    stop = paper_exit(paper, "long", Decimal(100), Decimal("97.9"))
    assert stop is not None and (stop.signal, stop.reason) == ("exit", PAPER_STOP_LOSS)
    take = paper_exit(paper, "short", Decimal(100), Decimal(95))
    assert take is not None and take.reason == PAPER_TAKE_PROFIT
    assert paper_exit(paper, "long", Decimal(100), Decimal(101)) is None
    assert paper_exit(_paper(None, None), "long", Decimal(100), Decimal(50)) is None


def test_an_entry_takes_the_tighter_stop_and_the_nearer_take_profit() -> None:
    paper = _paper("0.02", "0.05")
    own = Signal("enter", "long", "x", stop_loss_price=Decimal(99), take_profit_price=Decimal(110))
    entry = with_paper_levels(paper, own, Decimal(100))
    assert (entry.stop_loss_price, entry.take_profit_price) == (Decimal(99), Decimal(105))
    plain = with_paper_levels(paper, Signal("enter", "short", "x"), Decimal(100))
    assert (plain.stop_loss_price, plain.take_profit_price) == (Decimal(102), Decimal(95))
    assert with_paper_levels(_paper(None, None), own, Decimal(100)) == own


def _bars(*candles: tuple[float, float, float, float]) -> list[Bar]:
    return [Bar(T0 + timedelta(hours=k), *c) for k, c in enumerate(candles)]


def _trade(direction: str = "long", closed: int = 4) -> SimTrade:
    t = SimTrade(direction, T0, 100.0, None, entry_reason="x")
    t.closed_at, t.close_price, t.exit_reason = T0 + timedelta(hours=closed), 101.0, "signal"
    return t


BARS = _bars(
    (100, 100, 100, 100),  # the entry, at its close
    (100, 101, 99, 100),
    (100, 100, 97, 98),  # under 98: the 2% stop
    (98, 106, 98, 105),
    (105, 105, 100, 101),  # the strategy's exit
)


def test_the_backtest_cuts_a_trade_at_the_papers_stop_first() -> None:
    [t] = with_paper_exits([_trade()], BARS, 0.02, 0.05)
    assert (t.closed_at, t.exit_reason) == (T0 + timedelta(hours=2), PAPER_STOP_LOSS)
    assert t.close_price == pytest.approx(98 * (1 - STOP_SLIPPAGE))
    assert t.stop_loss_price == pytest.approx(98)


def test_the_backtest_cuts_at_the_take_profit_and_leaves_the_rest() -> None:
    [t] = with_paper_exits([_trade()], BARS, 0.05, 0.05)
    assert (t.closed_at, t.close_price, t.exit_reason) == (
        T0 + timedelta(hours=3),
        105,
        PAPER_TAKE_PROFIT,
    )
    # Neither reached before the strategy's own exit: kept as it was.
    [same] = with_paper_exits([_trade()], BARS, 0.5, 0.5)
    assert (same.closed_at, same.exit_reason) == (T0 + timedelta(hours=4), "signal")
    assert with_paper_exits([_trade()], BARS, None, None)[0].exit_reason == "signal"


def test_a_short_is_mirrored() -> None:
    bars = _bars((100, 100, 100, 100), (100, 103, 99, 102))  # over 102: the 2% stop
    [t] = with_paper_exits([_trade("short", 1)], bars, 0.02, None)
    assert t.exit_reason == PAPER_STOP_LOSS
    assert t.close_price == pytest.approx(102 * (1 + STOP_SLIPPAGE))
