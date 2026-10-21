"""Pure unit tests, no database."""

import pytest

from app.executors.supertrend_signals import supertrend, trendline_supertrends

CLOSES = [10.0, 10.0, 10.0, 11.0, 12.0, 13.0, 12.0, 9.0, 8.0]
HIGHS = [c + 1 for c in CLOSES]
LOWS = [c - 1 for c in CLOSES]


def test_the_bands_trail_the_price_and_a_close_under_the_up_band_turns_it_down() -> None:
    # ATR(2) is 2 until candle 7 (a true range of 4: 3), then 2.5; bands 1 ATR away.
    st = supertrend(HIGHS, LOWS, CLOSES, list[float | None](CLOSES), period=2, mult=1)
    assert st.trend == [None, 1, 1, 1, 1, 1, 1, -1, -1]
    # The up band only rises while the closes stay above it: 11 held at 12.
    assert st.line[1:7] == [8, 8, 9, 10, 11, 11]
    # 9 under the previous up band (11): down - the dn band, held at 12, then 10.5.
    assert st.line[7:] == [12, pytest.approx(10.5)]
    assert st.sell == [False] * 7 + [True, False]
    assert not any(st.buy)


def test_no_source_no_trend_and_a_run_starts_with_it() -> None:
    src: list[float | None] = [None, None, None, *CLOSES[3:]]
    st = supertrend(HIGHS, LOWS, CLOSES, src, period=2, mult=1)
    assert st.trend[:3] == [None] * 3 and st.line[:3] == [None] * 3
    # The run starts at candle 3: its own bands, an uptrend - no signal there.
    assert (st.trend[3], st.line[3]) == (1, 9)
    assert not st.buy[3] and not st.sell[3]


def test_the_two_instances_run_on_the_trendlines() -> None:
    n = 120
    closes = [100.0 + (k % 30) - (k // 30) * 3 for k in range(n)]
    upper, lower = trendline_supertrends([c + 1 for c in closes], [c - 1 for c in closes], closes)
    assert len(upper.line) == len(lower.line) == n
    assert any(x is not None for x in upper.line) and any(x is not None for x in lower.line)
