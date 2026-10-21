"""Pure unit tests, no database."""

from datetime import UTC, datetime, timedelta

import pytest

from app.backtest.bars import Bar
from app.backtest.bullrun import simulate
from app.executors.bullrun import (
    BREAK_EVEN_EXIT,
    STOP_LOSS_EXIT,
    TRAILING_STOP_EXIT,
    Indicators,
    entry_stop,
    exit_stop,
    higher_uptrend,
)

T0 = datetime(2026, 10, 1, tzinfo=UTC)
N = 206  # the signal candle is the last one, past the slow EMA's warm-up


def _series(
    dip_low: float = 99.5, mid: float = 95.0, last_close: float = 103.0, higher_up: bool = True
) -> tuple[list[float], list[float], list[float], Indicators]:
    """Fast EMA 100, slow 90, ATR 2; candles 101 (100.5-102), the one three
    before the last dipping to `dip_low`, the last closing at `last_close`."""
    highs, lows, closes = [102.0] * N, [100.5] * N, [101.0] * N
    lows[N - 3] = dip_low
    closes[-1] = last_close
    ind = Indicators([100.0] * N, [mid] * N, [90.0] * N, [2.0] * N, [higher_up] * N)
    return highs, lows, closes, ind


def test_pullback_close_opens_a_long_with_the_stop_capped_at_one_atr() -> None:
    # The dip's low 99.5 is further than 1 ATR (101): the stop sits at 101.
    assert entry_stop(*_series(), N - 1) == pytest.approx(101.0)


def test_no_entry_without_a_dip_an_uptrend_or_a_close_above_the_previous_high() -> None:
    assert entry_stop(*_series(dip_low=100.5), N - 1) is None
    assert entry_stop(*_series(mid=89.0), N - 1) is None
    assert entry_stop(*_series(higher_up=False), N - 1) is None
    assert entry_stop(*_series(last_close=102.0), N - 1) is None
    assert entry_stop(*_series(), 150) is None  # the slow EMA's warm-up


def test_higher_uptrend_reads_closed_four_hour_candles_from_hourly_ones() -> None:
    times = [T0 + timedelta(hours=h) for h in range(12)]
    # 4h closes (hours 3, 7, 11): 100, 110 (above the rising EMA), 90.
    closes = [100.0] * 4 + [110.0] * 4 + [90.0] * 4
    assert higher_uptrend(times, closes, "1h") == [False] * 7 + [True] * 4 + [False]
    assert higher_uptrend(times, closes, "15m") == [True] * 12  # no higher timeframe


def test_stop_moves_to_break_even_at_one_r_then_trails() -> None:
    assert exit_stop(100, 99, None, 1) == (99, STOP_LOSS_EXIT)
    assert exit_stop(100, 99, 100.9, 1) == (99, STOP_LOSS_EXIT)
    stop, reason = exit_stop(100, 99, 101, 1)
    assert stop == pytest.approx(100.2)
    assert reason == BREAK_EVEN_EXIT
    assert exit_stop(100, 99, 110, 1) == (107, TRAILING_STOP_EXIT)


def _uptrend_then_pullback() -> list[Bar]:
    """A steady rise (no candle closes above the previous high), a dip under
    the fast EMA, then a close above the dip's high: the long opens at 125.5
    on the last candle, its stop ~1 ATR under."""
    bars = []
    for t in range(250):
        close = 100 + 0.1 * t
        bars.append(Bar(T0 + timedelta(hours=t), close - 0.05, close + 0.3, close - 0.3, close))
    bars.append(Bar(T0 + timedelta(hours=250), 124.9, 125.0, 123.8, 124.0))  # the dip
    bars.append(Bar(T0 + timedelta(hours=251), 124.0, 125.6, 123.9, 125.5))  # the signal
    return bars


def _then(bars: list[Bar], *prices: tuple[float, float, float, float]) -> list[Bar]:
    step = timedelta(hours=1)
    return bars + [Bar(bars[-1].time + step * (k + 1), *p) for k, p in enumerate(prices)]


def test_backtest_rides_the_rally_and_exits_on_the_trailing_stop() -> None:
    rally = [(124.5 + k, 125.7 + k, 124.4 + k, 125.5 + k) for k in range(1, 11)]
    bars = _then(_uptrend_then_pullback(), *rally, (135.5, 135.6, 125.0, 126.0))
    trades = simulate(bars, "1h")
    assert [(t.entry_reason, t.exit_reason) for t in trades] == [
        ("pullback_entry", TRAILING_STOP_EXIT)
    ]
    assert trades[0].opened_at == bars[251].time
    assert trades[0].entry_price == pytest.approx(125.5)
    assert trades[0].close_price is not None and trades[0].close_price > 130


def _mirrored(bars: list[Bar]) -> list[Bar]:
    """The same candles upside down around 125: a downtrend and a rally."""
    return [Bar(b.time, 250 - b.open, 250 - b.low, 250 - b.high, 250 - b.close) for b in bars]


def test_backtest_shorts_the_rally_in_a_downtrend_mirrored() -> None:
    rally = [(124.5 + k, 125.7 + k, 124.4 + k, 125.5 + k) for k in range(1, 11)]
    bars = _mirrored(_then(_uptrend_then_pullback(), *rally, (135.5, 135.6, 125.0, 126.0)))
    assert simulate(bars, "1h") == []  # a long-only paper
    trades = simulate(bars, "1h", ("long", "short"))
    assert [(t.direction, t.entry_reason, t.exit_reason) for t in trades] == [
        ("short", "pullback_entry", TRAILING_STOP_EXIT)
    ]
    assert trades[0].entry_price == pytest.approx(124.5)
    stop = trades[0].stop_loss_price
    assert stop is not None and stop > trades[0].entry_price
    assert trades[0].close_price is not None and trades[0].close_price < 120


def test_backtest_short_stop_fills_above_the_open() -> None:
    bars = _mirrored(_then(_uptrend_then_pullback(), (124.0, 124.2, 123.0, 123.5)))
    trades = simulate(bars, "1h", ("short",), stop_slippage=0.0005)
    assert [(t.direction, t.exit_reason) for t in trades] == [("short", STOP_LOSS_EXIT)]
    assert trades[0].close_price == pytest.approx(126.0 * 1.0005)


def test_short_break_even_sits_under_the_entry() -> None:
    # A short at 100 (negated: -100), stop 101 (-101), the low reached 99 (-99).
    stop, reason = exit_stop(-100, -101, -99, 1)
    assert -stop == pytest.approx(99.8)
    assert reason == BREAK_EVEN_EXIT


def test_backtest_stop_gapped_through_fills_at_the_open() -> None:
    bars = _then(_uptrend_then_pullback(), (124.0, 124.2, 123.0, 123.5))
    trades = simulate(bars, "1h", stop_slippage=0.0005)
    assert [(t.entry_reason, t.exit_reason) for t in trades] == [("pullback_entry", STOP_LOSS_EXIT)]
    assert trades[0].close_price == pytest.approx(124.0 * 0.9995)
