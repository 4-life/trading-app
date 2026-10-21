"""Pure unit tests, no database."""

from datetime import UTC, datetime, timedelta

import pytest

from app.backtest.bars import Bar
from app.backtest.vwap import simulate
from app.executors.vwap import BUY_SIGNAL, SELL_SIGNAL, decide_signal
from app.executors.vwap_signals import Lines, session_vwap, signal_at

T0 = datetime(2026, 10, 1, tzinfo=UTC)


def test_vwap_is_volume_weighted_hlc3_reset_every_utc_day() -> None:
    times = [T0 + timedelta(hours=h) for h in (22, 23, 24, 25)]  # the third starts a day
    highs, lows, closes = (
        [12.0, 22.0, 32.0, 42.0],
        [9.0, 19.0, 29.0, 39.0],
        [12.0, 19.0, 29.0, 39.0],
    )
    vwap = session_vwap(times, highs, lows, closes, [1.0, 3.0, 2.0, 0.0])
    assert vwap[0] == pytest.approx(11.0)  # hlc3 (12 + 9 + 12) / 3
    assert vwap[1] == pytest.approx((11 * 1 + 20 * 3) / 4)
    assert vwap[2] == pytest.approx(30.0)  # reset: the new day's first candle only
    assert vwap[3] == pytest.approx(30.0)  # no volume: unchanged
    assert session_vwap(times[:1], highs[:1], lows[:1], closes[:1], [0.0]) == [None]


def test_signals_fire_once_when_the_close_moves_past_both_lines() -> None:
    ln = Lines(vwap=[100.0] * 5, ema=[100.0] * 5)
    closes = [100.0, 101.0, 102.0, 99.0, 98.0]
    assert [signal_at(closes, ln, i) for i in range(5)] == [None, "long", None, "short", None]
    between = Lines(vwap=[100.0, 100.0], ema=[102.0, 102.0])  # above the VWAP, under the EMA
    assert signal_at([99.0, 101.0], between, 1) is None
    assert signal_at([101.0, 103.0], Lines([None, None], [100.0, 100.0]), 1) is None  # no VWAP


def test_flat_each_signal_opens_once_long_only_or_both() -> None:
    buy = decide_signal(None, "long", False, "long")
    assert buy is not None and (buy.signal, buy.direction, buy.reason) == (
        "enter",
        "long",
        BUY_SIGNAL,
    )
    assert buy.stop_loss_price is None
    assert decide_signal(None, "short", False, "long") is None  # long-only
    sell = decide_signal(None, "short", False, "both")
    assert sell is not None and (sell.direction, sell.reason) == ("short", SELL_SIGNAL)
    assert decide_signal(None, "long", True, "long") is None  # once per signal
    assert decide_signal(None, None, False, "both") is None


def test_the_opposite_signal_closes_the_position() -> None:
    sell = decide_signal("long", "short", False, "long")
    assert sell is not None and (sell.signal, sell.direction, sell.reason) == (
        "exit",
        "long",
        SELL_SIGNAL,
    )
    buy = decide_signal("short", "long", False, "both")
    assert buy is not None and (buy.signal, buy.direction, buy.reason) == (
        "exit",
        "short",
        BUY_SIGNAL,
    )
    assert decide_signal("long", "long", False, "long") is None
    assert decide_signal("long", None, False, "long") is None


def _bars(prices: list[tuple[float, float, float, float]]) -> list[Bar]:
    return [Bar(T0 + timedelta(hours=i), *p, volume=1.0) for i, p in enumerate(prices)]


# BUY at 5, SELL at 7.
_PRICES = [
    *[(100.0, 100.0, 100.0, 100.0)] * 5,
    (100.0, 100.3, 100.0, 100.3),  # BUY
    (100.3, 100.35, 100.15, 100.2),
    (100.2, 100.2, 100.0, 100.05),  # SELL
    (100.05, 100.1, 100.05, 100.075),
]


def test_backtest_buys_and_sells_on_the_signals() -> None:
    trades = simulate(_bars(_PRICES), "long")
    assert [(t.direction, t.entry_reason, t.exit_reason) for t in trades] == [
        ("long", BUY_SIGNAL, SELL_SIGNAL)
    ]
    assert (trades[0].entry_price, trades[0].close_price) == (100.3, 100.05)
    assert trades[0].stop_loss_price is None


def test_backtest_reverses_on_the_signal_when_both() -> None:
    trades = simulate(_bars(_PRICES), "both")
    assert [(t.direction, t.exit_reason, t.entry_price) for t in trades] == [
        ("long", SELL_SIGNAL, 100.3),
        ("short", "open_at_end", 100.05),
    ]
