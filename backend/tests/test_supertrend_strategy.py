"""Pure unit tests, no database."""

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from app.backtest import supertrend as backtest
from app.backtest.bars import Bar
from app.executors.supertrend import SUPERTREND_BUY, SUPERTREND_SELL, decide_signal
from app.executors.supertrend_signals import Supertrend
from app.papers.models import Paper

T0 = datetime(2026, 10, 1, tzinfo=UTC)


def test_a_long_paper_buys_on_buy_and_closes_on_sell() -> None:
    buy = decide_signal("long", False, buy=True, sell=False, entered_on_signal=False)
    assert buy is not None and (buy.signal, buy.direction, buy.reason) == (
        "enter",
        "long",
        SUPERTREND_BUY,
    )
    assert buy.stop_loss_price is None and buy.take_profit_price is None
    assert decide_signal("long", False, True, False, entered_on_signal=True) is None  # once
    assert decide_signal("long", False, False, True, False) is None  # a sell opens no short
    sell = decide_signal("long", True, False, True, False)
    assert sell is not None and (sell.signal, sell.reason) == ("exit", SUPERTREND_SELL)
    assert decide_signal("long", True, True, False, False) is None


def test_a_short_paper_sells_on_sell_and_closes_on_buy() -> None:
    sell = decide_signal("short", False, False, True, False)
    assert sell is not None and (sell.signal, sell.direction, sell.reason) == (
        "enter",
        "short",
        SUPERTREND_SELL,
    )
    assert decide_signal("short", False, True, False, False) is None  # a buy opens no long
    buy = decide_signal("short", True, True, False, False)
    assert buy is not None and (buy.signal, buy.reason) == ("exit", SUPERTREND_BUY)


def _bars(closes: list[float]) -> list[Bar]:
    return [Bar(T0 + timedelta(hours=k), c, c, c, c) for k, c in enumerate(closes)]


def _stub(monkeypatch: pytest.MonkeyPatch, buys: list[int], sells: list[int], n: int) -> list[str]:
    """`signals` returns a Buy on `buys`, a Sell on `sells`; the directions it was asked for."""
    asked: list[str] = []

    def fake(_h: Any, _l: Any, _c: Any, direction: str) -> Supertrend:
        asked.append(direction)
        buy, sell = [k in buys for k in range(n)], [k in sells for k in range(n)]
        return Supertrend([None] * n, [None] * n, buy, sell)

    monkeypatch.setattr(backtest, "signals", fake)
    return asked


def test_the_backtest_trades_the_long_on_its_signals(monkeypatch: pytest.MonkeyPatch) -> None:
    asked = _stub(monkeypatch, [1, 4], [3], 6)
    trades = backtest.simulate(_bars([10, 11, 12, 13, 14, 15]), "long")
    assert asked == ["long"]  # the lower trendline's
    assert [(t.entry_price, t.close_price, t.exit_reason) for t in trades] == [
        (11, 13, SUPERTREND_SELL),
        (14, 15, "open_at_end"),
    ]
    assert all(t.stop_loss_price is None for t in trades)


def test_the_backtest_trades_the_short_on_its_signals(monkeypatch: pytest.MonkeyPatch) -> None:
    asked = _stub(monkeypatch, [3], [1], 5)
    trades = backtest.simulate(_bars([10, 11, 12, 13, 14]), "short")
    assert asked == ["short"]  # the upper trendline's
    assert [(t.direction, t.entry_price, t.close_price, t.exit_reason) for t in trades] == [
        ("short", 11, 13, SUPERTREND_BUY)
    ]


def test_an_averaging_paper_buys_on_every_buy_signal(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub(monkeypatch, [1, 4], [3], 6)
    paper = Paper(direction="long")
    entries = backtest.entry_signals(paper, _bars([10, 11, 12, 13, 14, 15]))
    assert [t.entry_price for t in entries] == [11, 14]
    # A short one: on every sell signal.
    shorts = backtest.entry_signals(Paper(direction="short"), _bars([10, 11, 12, 13, 14, 15]))
    assert [(t.direction, t.entry_price) for t in shorts] == [("short", 13)]
