"""Pure unit tests, no database."""

from datetime import UTC, datetime, timedelta

from app.market_data.shock_state import blocking
from app.market_data.shocks import Series, Shock, market_shocks

T0 = datetime(2026, 10, 1, tzinfo=UTC)
STEP = timedelta(minutes=15)
N = 500  # candles


def _flat(price: float = 100.0, volume: float = 10.0) -> Series:
    return {T0 + k * STEP: (price, volume) for k in range(N)}


def _move(series: Series, at: int, move: float, volume: float, candles: int = 4) -> None:
    """From candle `at` on, `move` over `candles` candles at `volume` each, held after."""
    base = series[T0 + (at - 1) * STEP][0]
    for k in range(at, N):
        step = min(k - at + 1, candles)
        vol = volume if k - at < candles else series[T0 + k * STEP][1]
        series[T0 + k * STEP] = (base * (1 + move * step / candles), vol)


def _market(move: float, coins_move: float, volume: float = 50.0) -> dict[str, Series]:
    series = {"BTC": _flat(), "ETH": _flat(), "SOL": _flat(), "BNB": _flat()}
    _move(series["BTC"], 150, move, volume)
    for coin in ("ETH", "SOL", "BNB"):
        _move(series[coin], 150, coins_move, volume)
    return series


def test_a_market_panic_needs_btc_speed_breadth_and_volume() -> None:
    [shock] = market_shocks(_market(-0.03, -0.03), "ETH", STEP, T0)
    # -0.75% a candle from 150: past -2% in 1h at the third (152).
    assert (shock.time, shock.kind, shock.scope) == (T0 + 152 * STEP, "panic", "market")
    assert shock.detected_at == T0 + 153 * STEP  # at that candle's close
    assert "3 of 3 coins down" in shock.text
    # The other coins holding: no breadth, no panic.
    assert [s for s in market_shocks(_market(-0.03, 0.0), "BTC", STEP, T0)] == []
    # Usual volume: no panic.
    assert market_shocks(_market(-0.03, -0.03, volume=10.0), "BTC", STEP, T0) == []


def test_a_market_bullrun_is_the_panic_mirrored() -> None:
    [shock] = market_shocks(_market(0.03, 0.03), "BTC", STEP, T0)
    assert (shock.kind, shock.scope) == ("bullrun", "market")


def test_a_coin_bullrun_beats_btc_on_its_own_volume() -> None:
    series = {"BTC": _flat(), "HYPE": _flat(), "ETH": _flat(), "SOL": _flat()}
    _move(series["HYPE"], 150, 0.06, 40.0, candles=8)
    shocks = market_shocks(series, "HYPE", STEP, T0)
    assert [(s.kind, s.scope) for s in shocks] == [("bullrun", "coin")]
    # Not on another coin's chart.
    assert market_shocks(series, "ETH", STEP, T0) == []


def test_one_event_per_kind_within_the_cooldown() -> None:
    series = _market(-0.03, -0.03)
    _move(series["BTC"], 170, -0.03, 60.0)
    for coin in ("ETH", "SOL", "BNB"):
        _move(series[coin], 170, -0.03, 60.0)
    # 170 is 5h after 150: inside the 6h cooldown.
    assert len(market_shocks(series, "BTC", STEP, T0)) == 1


def test_a_slide_over_four_hours_is_a_panic_too() -> None:
    # -4% over 16 candles: -1% an hour, under the 1h speed; -4% in 4h.
    series = {"BTC": _flat(), "ETH": _flat(), "SOL": _flat(), "BNB": _flat()}
    for coin in series:
        _move(series[coin], 400, -0.04, 30.0, candles=16)
    [shock] = market_shocks(series, "BTC", STEP, T0)
    assert (shock.kind, shock.scope) == ("panic", "market")
    assert "in 4h" in shock.text


def test_without_enough_coins_breadth_is_skipped() -> None:
    series = {"BTC": _flat(), "HYPE": _flat()}
    _move(series["BTC"], 150, -0.03, 50.0)
    [shock] = market_shocks(series, "BTC", STEP, T0)
    assert (shock.kind, "no breadth" in shock.text) == ("panic", True)


def test_a_panic_blocks_longs_and_a_bullrun_shorts() -> None:
    panic = Shock(T0, T0 + STEP, "panic", "market", "")
    bullrun = Shock(T0 + STEP, T0 + 2 * STEP, "bullrun", "coin", "")
    assert blocking([panic, bullrun], "long") == panic
    assert blocking([panic, bullrun], "short") == bullrun
    assert blocking([panic], "short") is None
