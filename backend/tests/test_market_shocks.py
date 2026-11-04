"""Pure unit tests, no database."""

from datetime import UTC, datetime, timedelta
from random import Random

from app.market_data.shock_state import _alert_text, entry_blocked, exit_held
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
    _move(series["HYPE"], 150, 0.06, 40.0)  # +6% within an hour
    shocks = market_shocks(series, "HYPE", STEP, T0)
    assert [(s.kind, s.scope) for s in shocks] == [("bullrun", "coin")]
    assert "in 1h" in shocks[0].text
    # Not on another coin's chart.
    assert market_shocks(series, "ETH", STEP, T0) == []


def test_a_coins_slow_climb_isnt_a_shock() -> None:
    # +6% vs BTC over 4h, on the volume - but 1.5% an hour, under COIN_SPEED.
    series = {"BTC": _flat(), "HYPE": _flat(), "ETH": _flat(), "SOL": _flat()}
    _move(series["HYPE"], 150, 0.06, 40.0, candles=16)
    assert market_shocks(series, "HYPE", STEP, T0) == []


def test_one_event_per_kind_within_the_cooldown() -> None:
    series = _market(-0.03, -0.03)
    _move(series["BTC"], 170, -0.03, 60.0)
    for coin in ("ETH", "SOL", "BNB"):
        _move(series[coin], 170, -0.03, 60.0)
    # 170 is 5h after 150: inside the 6h cooldown.
    assert len(market_shocks(series, "BTC", STEP, T0)) == 1


def test_a_shock_still_going_is_new_only_scanned_from_inside_it() -> None:
    # The panic from 152 holds past -2% in 1h for a while: scanned from 160
    # it's "new" at 160 (the alerts' spam); scanned from before it, one event.
    series = _market(-0.03, -0.03)
    _move(series["BTC"], 160, -0.03, 60.0)
    for coin in ("ETH", "SOL", "BNB"):
        _move(series[coin], 160, -0.03, 60.0)
    [late] = market_shocks(series, "BTC", STEP, T0 + 161 * STEP)
    assert late.time > T0 + 152 * STEP
    [shock] = market_shocks(series, "BTC", STEP, T0)
    assert shock.time == T0 + 152 * STEP


def test_a_slide_over_four_hours_is_a_panic_too() -> None:
    # -4% over 16 candles: -1% an hour, under the 1h speed; -4% in 4h. From
    # 200: too little history yet for the unusual-move rule.
    series = {"BTC": _flat(), "ETH": _flat(), "SOL": _flat(), "BNB": _flat()}
    for coin in series:
        _move(series[coin], 200, -0.04, 30.0, candles=16)
    [shock] = market_shocks(series, "BTC", STEP, T0)
    assert (shock.kind, shock.scope) == ("panic", "market")
    assert "in 4h" in shock.text


def test_without_enough_coins_breadth_is_skipped() -> None:
    series = {"BTC": _flat(), "HYPE": _flat()}
    _move(series["BTC"], 150, -0.03, 50.0)
    [shock] = market_shocks(series, "BTC", STEP, T0)
    assert (shock.kind, "no breadth" in shock.text) == ("panic", True)


def _noisy(seed: int, sd: float = 0.001) -> Series:
    """A price jittering `sd` a candle around 100, at the flat volume."""
    random = Random(seed)
    return {T0 + k * STEP: (100.0 * (1 + random.gauss(0, sd)), 10.0) for k in range(N)}


def _noisy_market() -> dict[str, Series]:
    return {"BTC": _noisy(1), "ETH": _noisy(2), "SOL": _noisy(3), "BNB": _noisy(4)}


def test_a_drop_unusual_for_the_coin_is_its_panic_whatever_btc_does() -> None:
    # -3% in 30m, BTC flat: far beyond ETH's normal, under the 5% against BTC.
    series = _noisy_market()
    _move(series["ETH"], 450, -0.03, 40.0, candles=2)
    [shock] = market_shocks(series, "ETH", STEP, T0)
    assert (shock.kind, shock.scope) == ("panic", "coin")
    assert shock.time in (T0 + 450 * STEP, T0 + 451 * STEP)
    assert "its normal" in shock.text
    # Not on another coin's chart.
    assert market_shocks(series, "SOL", STEP, T0) == []


def test_the_same_drop_is_normal_for_a_wild_coin() -> None:
    series = _noisy_market()
    series["ETH"] = _noisy(2, sd=0.01)
    _move(series["ETH"], 450, -0.03, 40.0, candles=2)
    assert market_shocks(series, "ETH", STEP, T0) == []


def test_an_unusual_move_needs_the_volume() -> None:
    series = _noisy_market()
    _move(series["ETH"], 450, -0.03, 10.0, candles=2)
    assert market_shocks(series, "ETH", STEP, T0) == []


def test_btcs_unusual_move_is_the_markets_with_breadth() -> None:
    series = _noisy_market()
    for coin in series:
        _move(series[coin], 450, -0.015, 40.0, candles=2)
    # On any chart, the coins' own unusual moves held back by it.
    [shock] = market_shocks(series, "ETH", STEP, T0)
    assert (shock.kind, shock.scope) == ("panic", "market")
    assert "3 of 3 coins down" in shock.text


def test_btcs_unusual_move_alone_is_on_its_chart_only() -> None:
    series = _noisy_market()
    _move(series["BTC"], 450, -0.015, 40.0, candles=2)
    [shock] = market_shocks(series, "BTC", STEP, T0)
    assert (shock.kind, shock.scope) == ("panic", "coin")
    assert market_shocks(series, "ETH", STEP, T0) == []


def test_a_panic_blocks_longs_and_a_bullrun_shorts_for_six_hours() -> None:
    panic = Shock(T0, T0 + STEP, "panic", "market", "")
    bullrun = Shock(T0 + STEP, T0 + 2 * STEP, "bullrun", "coin", "")
    at = T0 + 3 * STEP
    assert entry_blocked([panic, bullrun], "long", at) == panic
    assert entry_blocked([panic, bullrun], "short", at) == bullrun
    assert entry_blocked([panic], "short", at) is None
    assert entry_blocked([panic], "long", T0) is None  # before it was detected
    assert entry_blocked([panic], "long", T0 + STEP + timedelta(hours=6)) is None


def test_a_bullrun_holds_a_longs_exit_and_a_panic_a_shorts() -> None:
    panic = Shock(T0, T0 + STEP, "panic", "market", "")
    bullrun = Shock(T0, T0 + STEP, "bullrun", "coin", "")
    at = T0 + 2 * STEP
    assert exit_held([bullrun], "long", at) == bullrun
    assert exit_held([panic], "short", at) == panic
    assert exit_held([panic], "long", at) is None


def test_the_alert_says_what_happened_and_what_is_held_back() -> None:
    t = datetime(2026, 10, 29, 20, 44, tzinfo=UTC)
    panic = Shock(t - STEP, t, "panic", "market", "BTC -2.5% in 1h")
    assert _alert_text("BTC", panic) == (
        "market panic detected 2026-10-29 20:44 UTC: BTC -2.5% in 1h"
        " - new longs held back until 02:44 UTC"
    )
    bullrun = Shock(t - STEP, t, "bullrun", "coin", "HYPE +6%")
    assert _alert_text("HYPE", bullrun).startswith("HYPE bullrun detected")
