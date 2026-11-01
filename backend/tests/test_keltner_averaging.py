"""Pure unit tests, no database."""

from datetime import UTC, datetime, timedelta

from app.backtest.averaging import Rules, simulate
from app.backtest.bars import Bar, SimTrade, exit_at
from app.executors.keltner_averaging import KeltnerGuard
from app.executors.position_management import TAKE_PROFIT_EXIT

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


def test_a_loss_never_closes_the_position_only_a_sell_above_the_take_profit() -> None:
    # In at 100, down to 97 (no dip add before 95), back up: no stop - it
    # holds until the Sell at 4 with the take-profit ($3) reached.
    closes = [100.0, 98.0, 97.0, 101.0, 104.0, 104.0]
    bars = _bars(closes)
    # The Supertrend's line moved by then: not a broken first sell.
    line: list[float | None] = [90.0, 90.0, 90.0, 91.0, 92.0, 92.0]
    g = _guard(closes, line=line, sell=frozenset({4}))
    exits = [exit_at("long", bars[4], "keltner_sell")]
    [t] = simulate(bars, [], RULES, signals_held=[_buy(0, 100)], exits=exits, guard=g)
    assert (t.closed_at, t.exit_reason) == (bars[4].time, f"{TAKE_PROFIT_EXIT}:keltner_sell")
