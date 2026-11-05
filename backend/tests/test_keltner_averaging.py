"""Pure unit tests, no database."""

from datetime import UTC, datetime, timedelta
from math import sin

from app.backtest.averaging import Rules, simulate
from app.backtest.bars import Bar, SimTrade, exit_at
from app.executors.keltner_averaging import KeltnerGuard, keltner_guard
from app.executors.position_management import TAKE_PROFIT_EXIT
from app.executors.supertrend import signals as supertrend_signals
from app.market_data.shocks import Shock

T0 = datetime(2026, 10, 1, tzinfo=UTC)
# $10 at 10x ($100 at 100: one unit), TP 30% of the margin ($3); adds at half the margin lost (95).
RULES = Rules(10, 10, 3, 10, 0.3, 0.4, 0.2)


def _guard(
    closes: list[float],
    trend: int = -1,
    line: list[float | None] | None = None,
    sell: frozenset[int] = frozenset(),
) -> KeltnerGuard:
    n = len(closes)
    flat: list[float | None] = [90.0] * n
    return KeltnerGuard(
        closes,
        [trend] * n,
        line if line is not None else flat,
        [False] * n,
        [i in sell for i in range(n)],
    )


def test_a_both_paper_reads_the_long_line_a_short_paper_the_short_one() -> None:
    closes = [100 + 10 * sin(k / 9) + (k % 5) for k in range(400)]
    highs, lows = [c + 1 for c in closes], [c - 1 for c in closes]
    long_line = supertrend_signals(highs, lows, closes, "long")
    short_line = supertrend_signals(highs, lows, closes, "short")
    assert long_line.line != short_line.line
    for direction, st in (("long", long_line), ("both", long_line), ("short", short_line)):
        g = keltner_guard(direction, highs, lows, closes)
        assert (g.trend, g.line) == (st.trend, st.line)


def _bars(closes: list[float]) -> list[Bar]:
    return [Bar(T0 + timedelta(hours=k), c, c + 0.5, c - 0.5, c) for k, c in enumerate(closes)]


def _buy(k: int, price: float) -> SimTrade:
    return SimTrade("long", T0 + timedelta(hours=k), price, None, entry_reason="keltner_buy")


def test_a_long_opens_on_a_red_supertrend_only() -> None:
    g = _guard([100.0, 100.0])
    assert g.may_open("long", 0)
    assert not g.may_open("short", 0)
    green = _guard([100.0], trend=1)
    assert green.may_open("short", 0)
    assert not green.may_open("long", 0)


def test_the_first_sell_is_broken_while_the_supertrend_line_stays() -> None:
    g = _guard([100.0] * 4, sell=frozenset({1, 2}))
    assert g.sell_broken("long", 1, 0)
    assert not g.sell_broken("long", 2, 0)  # the second
    moved = _guard([100.0] * 2, line=[90.0, 91.0], sell=frozenset({1}))
    assert not moved.sell_broken("long", 1, 0)


def test_the_backtest_opens_on_red_only() -> None:
    closes = [100.0, 100.0, 100.0]
    g = _guard(closes)
    g = KeltnerGuard(g.closes, [1, -1, -1], g.line, g.buy, g.sell)
    [t] = simulate(_bars(closes), [], RULES, signals_held=[_buy(0, 100), _buy(1, 100)], guard=g)
    assert t.opened_at == T0 + timedelta(hours=1)


def test_the_backtest_passes_the_broken_first_sell() -> None:
    closes = [100.0, 104.0, 105.0, 105.0]
    bars = _bars(closes)
    g = _guard(closes, sell=frozenset({1, 2}))
    exits = [exit_at("long", bars[1], "keltner_sell"), exit_at("long", bars[2], "keltner_sell")]
    [t] = simulate(bars, [], RULES, signals_held=[_buy(0, 100)], exits=exits, guard=g)
    assert (t.closed_at, t.exit_reason) == (bars[2].time, f"{TAKE_PROFIT_EXIT}:keltner_sell")


def test_a_signal_add_needs_one_percent_below_the_last_buy_and_at_most_five() -> None:
    g = _guard([99.5, 99.0, 98.0])
    assert not g.signal_add_allowed("long", 0, 100.0, 0)  # 0.5% below
    assert g.signal_add_allowed("long", 1, 100.0, 0)  # 1% below
    assert not g.signal_add_allowed("long", 2, 100.0, 5)  # the sixth


def test_a_strength_add_on_the_supertrend_flip_in_profit() -> None:
    g = _guard([100.0, 101.0])
    g = KeltnerGuard(g.closes, [-1, 1], g.line, g.buy, g.sell)
    assert g.strength_add("long", 1, pnl=1.0)
    assert not g.strength_add("long", 1, pnl=-1.0)
    assert not g.strength_add("short", 1, pnl=1.0)  # a short's flip is to red


def test_the_backtest_keeps_the_core_and_spaces_the_signal_adds() -> None:
    # In at 100 (the core); a Buy at 1 (99.5) is too close; at 2 (98.5) a
    # signal add; at 3 the price is back at 100: the add sells at the core's
    # price, the core is kept.
    closes = [100.0, 99.5, 98.5, 100.0, 100.0]
    g = _guard(closes)
    signals = [_buy(0, 100), _buy(1, 99.5), _buy(2, 98.5)]
    [t] = simulate(_bars(closes), [], RULES, signals_held=signals, guard=g)
    assert [(f.side, f.time) for f in t.fills] == [
        ("buy", T0),
        ("buy", T0 + timedelta(hours=2)),
        ("sell", T0 + timedelta(hours=3)),
    ]
    assert t.fills[2].price == 100.0


def test_the_backtest_adds_on_strength_and_never_unwinds_it() -> None:
    # In at 100; the Supertrend flips green at 2 in profit (102): a core add.
    closes = [100.0, 101.0, 102.0, 105.0, 105.0]
    g = _guard(closes)
    g = KeltnerGuard(g.closes, [-1, -1, 1, 1, 1], g.line, g.buy, g.sell)
    [t] = simulate(_bars(closes), [], RULES, signals_held=[_buy(0, 100)], guard=g)
    assert [(f.side, f.time, f.price) for f in t.fills] == [
        ("buy", T0, 100.0),
        ("buy", T0 + timedelta(hours=2), 102.0),
    ]


def test_a_sell_inside_a_bullrun_waits_for_the_next_one() -> None:
    # A bullrun detected at hour 3: the Sell at 4 (close 5h) waits; the one at
    # 10 (close 11h, past 3h + 6h) closes.
    closes = [100.0, 102.0, 104.0, 105.0, 106.0] + [106.0] * 7
    bars = _bars(closes)
    line: list[float | None] = [90.0, 91.0, *([92.0] * 10)]
    g = _guard(closes, line=line, sell=frozenset({4, 10}))
    exits = [exit_at("long", bars[4], "keltner_sell"), exit_at("long", bars[10], "keltner_sell")]
    bullrun = Shock(T0 + timedelta(hours=2), T0 + timedelta(hours=3), "bullrun", "market", "")
    [t] = simulate(
        bars, [], RULES, signals_held=[_buy(0, 100)], exits=exits, guard=g, shocks=[bullrun]
    )
    assert t.closed_at == bars[10].time


def test_a_panic_holds_back_the_signal_and_strength_adds() -> None:
    # As the core-and-spacing test - its signal add at 2 - and a strength
    # flip at 3, with a panic detected after the entry (1h30): neither add comes.
    closes = [100.0, 99.5, 98.5, 101.0, 101.0]
    g = _guard(closes)
    g = KeltnerGuard(g.closes, [-1, -1, -1, 1, 1], g.line, g.buy, g.sell)
    signals = [_buy(0, 100), _buy(1, 99.5), _buy(2, 98.5)]
    panic = Shock(T0 + timedelta(hours=1), T0 + timedelta(minutes=90), "panic", "market", "")
    [t] = simulate(_bars(closes), [], RULES, signals_held=signals, guard=g, shocks=[panic])
    assert [f.side for f in t.fills] == ["buy"]
    # Without it: both.
    [free] = simulate(_bars(closes), [], RULES, signals_held=signals, guard=g)
    assert [f.side for f in free.fills] == ["buy", "buy", "sell", "buy"]
