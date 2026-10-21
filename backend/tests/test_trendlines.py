"""Pure unit tests, no database."""

import pytest

from app.executors.trendlines import slopes, trendlines

LENGTH = 2


def test_a_pivot_high_starts_a_falling_line_and_a_close_above_it_breaks_up() -> None:
    # A pivot high of 10 at candle 2, known at candle 4; the slope there is 0.5
    # (stdev of the closes 4, 5 = 0.5, / 2 x 2). The line: 10 at its pivot,
    # -0.5 a candle - 9 projected to candle 4, 8.5 at 5, 8 at 6.
    highs = [5.0, 6.0, 10.0, 6.0, 5.0, 5.0, 9.0, 9.0]
    lows = [4.0, 5.0, 9.0, 5.0, 4.0, 4.0, 8.0, 8.0]
    closes = [4.5, 5.5, 9.5, 4.0, 5.0, 4.5, 8.4, 8.6]
    t = trendlines(highs, lows, closes, LENGTH, mult=2, method="stdev")
    assert t.upper[:4] == [None] * 4
    assert t.upper[4:7] == [pytest.approx(9.0), pytest.approx(8.5), pytest.approx(8.0)]
    # 8.4 > 8 at candle 6: the break, once - not again at 7.
    assert t.break_up == [False] * 6 + [True, False]


def test_a_pivot_low_starts_a_rising_line_and_a_close_under_it_breaks_down() -> None:
    # Mirrored: a pivot low of 1 at candle 2, known at 4, a 0.5 slope.
    highs = [6.0, 5.0, 2.0, 5.0, 6.0, 6.0, 3.0, 3.0]
    lows = [5.0, 4.0, 1.0, 4.0, 5.0, 5.0, 2.0, 2.0]
    closes = [5.5, 4.5, 1.5, 6.0, 5.0, 5.5, 2.6, 2.4]
    t = trendlines(highs, lows, closes, LENGTH, mult=2, method="stdev")
    assert t.lower[4:7] == [pytest.approx(2.0), pytest.approx(2.5), pytest.approx(3.0)]
    assert t.break_dn == [False] * 6 + [True, False]


def test_slopes_by_method() -> None:
    highs, lows = [2.0, 3.0, 4.0, 5.0], [1.0, 2.0, 3.0, 4.0]
    closes = [1.0, 2.0, 3.0, 4.0]
    # ATR(2): true ranges 1, 2, 2, 2 -> 1.5, then Wilder 1.75, 1.875; / 2.
    assert slopes(highs, lows, closes, 2, mult=1, method="atr") == [
        None,
        pytest.approx(0.75),
        pytest.approx(0.875),
        pytest.approx(0.9375),
    ]
    # A straight line rising 1 a candle: the regression's slope 1, halved.
    assert slopes(highs, lows, closes, 2, mult=1, method="linreg")[1:] == [pytest.approx(0.5)] * 3
