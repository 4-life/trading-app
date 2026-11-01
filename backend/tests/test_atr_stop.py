"""Pure unit tests, no database."""

import pytest

from app.executors.atr_stop import atr_stop


def _candles(
    n: int, high: float, low: float, close: float
) -> tuple[list[float], list[float], list[float]]:
    return [high] * n, [low] * n, [close] * n


def test_a_longs_stop_is_under_the_low_by_atr_times_the_multiplier() -> None:
    # Every true range 2 (102 - 100): ATR 2, x1.2 = 2.4.
    highs, lows, closes = _candles(21, 102.0, 100.0, 101.0)
    assert atr_stop("long", highs, lows, closes) == pytest.approx(100.0 - 2.4)
    assert atr_stop("short", highs, lows, closes) == pytest.approx(102.0 + 2.4)


def test_the_true_range_counts_a_gap_from_the_previous_close() -> None:
    # The last candle gapped up: its range 2, but 105 - 101 = 4 from the close before.
    highs, lows, closes = _candles(21, 102.0, 100.0, 101.0)
    highs[-1], lows[-1], closes[-1] = 105.0, 103.0, 104.0
    atr = (19 * 2 + 4) / 20
    assert atr_stop("long", highs, lows, closes) == pytest.approx(103.0 - atr * 1.2)


def test_none_before_enough_candles() -> None:
    assert atr_stop("long", *_candles(20, 102.0, 100.0, 101.0)) is None


def test_its_length_and_multiplier_can_be_set() -> None:
    highs, lows, closes = _candles(15, 102.0, 100.0, 101.0)
    assert atr_stop("long", highs, lows, closes, length=14, multiplier=1.5) == pytest.approx(97.0)
