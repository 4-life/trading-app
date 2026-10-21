"""Pure unit tests, no database."""

from app.executors.trend_bands import WARMUP_BARS, _breaks_up, atr, trend_bands


def test_atr_is_seeded_with_the_simple_average() -> None:
    highs, lows, closes = [102.0] * 5, [100.0] * 5, [101.0] * 5
    assert atr(highs, lows, closes, 3) == [None, None, 2.0, 2.0, 2.0]


def test_trend_flips_on_a_close_across_a_band() -> None:
    n = WARMUP_BARS + 60
    highs, lows, closes = [100.5] * n, [99.5] * n, [100.0] * n
    up, down = WARMUP_BARS + 50, WARMUP_BARS + 55
    closes[up] = highs[up] = 110.0  # above the upper band (~100 + 3 x 1)
    closes[down] = lows[down] = 90.0  # below the lower band
    state = trend_bands(highs, lows, closes, [1.0] * n).state
    assert state[up - 1] == 0
    assert state[up:down] == [1] * 5
    assert state[down] == -1


def test_no_bands_or_trend_during_the_warm_up() -> None:
    n = WARMUP_BARS + 10
    highs, lows, closes = [100.5] * n, [99.5] * n, [100.0] * n
    early = WARMUP_BARS - 50  # ATR ready, the bands not yet
    closes[early] = highs[early] = 110.0
    b = trend_bands(highs, lows, closes, [1.0] * n)
    assert b.atr[early] is not None
    assert b.upper[WARMUP_BARS - 1] is None and b.upper[WARMUP_BARS] is not None
    assert set(b.state) == {0}


def test_break_up_fires_on_the_first_close_above_the_anchored_vwap() -> None:
    # n = 2: the pivot high 5 (candle 3) is confirmed on candle 5; the VWAP
    # of the previous highs restarts after each local high: 4 on candle 5,
    # (4 + 3) / 2 = 3.5 on candle 6.
    highs = [1.0, 2.0, 3.0, 5.0, 4.0, 3.0, 3.5, 3.0]
    volumes = [1.0] * len(highs)

    def breaks(close: float, state: list[int] | None = None) -> list[bool]:
        closes = [0.0] * 6 + [close, close]
        return _breaks_up(highs, closes, volumes, state or [1] * len(highs), 2)

    assert breaks(3.6) == [False] * 6 + [True, False]  # once per pivot
    assert breaks(3.4) == [False] * len(highs)
    # A flip on candle 6 disarms it: no signal after the flip back.
    assert breaks(3.6, [1] * 6 + [-1, 1]) == [False] * len(highs)
