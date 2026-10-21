"""Pure unit tests, no database."""

from app.executors.liquidity_swings import liquidity_zones


def _v(low_at: int, n: int = 60) -> tuple[list[float], list[float], list[float]]:
    """Flat at 100 with a gentle V bottom (95) at `low_at`: candles 2 wide, so
    the candles next to the bottom trade into its range."""
    closes = [100.0 - max(0.0, 5.0 - 0.5 * abs(i - low_at)) for i in range(n)]
    return [c + 1 for c in closes], [c - 1 for c in closes], closes


def test_swing_low_zone_is_the_pivot_candle_full_range() -> None:
    highs, lows, closes = _v(25)
    lows_ = [z for z in liquidity_zones(highs, lows, closes, length=5) if z.kind == "low"]
    assert lows_ and lows_[0].pivot_index == 25
    assert (lows_[0].btm, lows_[0].top) == (lows[25], highs[25])


def test_zone_is_confirmed_once_its_count_exceeds_the_filter() -> None:
    highs, lows, closes = _v(25)
    z = next(z for z in liquidity_zones(highs, lows, closes, length=5) if z.kind == "low")
    # the pivot is known 5 candles later; the next two candles (lagged by 5)
    # trade into its range -> count 2 > 1 two candles after that
    assert z.confirm_index == 25 + 5 + 2
    assert not z.broken_at_confirm


def test_close_below_a_swing_low_breaks_it() -> None:
    highs, lows, closes = _v(25)
    for i in range(45, 60):  # collapse well below the zone
        closes[i] = lows[i] = highs[i] = 50.0
    z = next(z for z in liquidity_zones(highs, lows, closes, length=5) if z.kind == "low")
    assert z.broken_index == 45
