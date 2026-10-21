"""Pure unit tests, no database."""

from datetime import UTC, datetime
from decimal import Decimal

from app.execution_engine.models import Position
from app.executors.position_management import AVERAGE_DOWN
from app.notifications.trades import leverage, price, trade_message
from app.papers.models import Paper

T0 = datetime(2026, 10, 4, tzinfo=UTC)


def _paper() -> Paper:
    return Paper(id=12, asset="BTC", timeframe="1h", executor="vwap")


def _position(**kw: object) -> Position:
    base: dict[str, object] = {
        "mode": "demo",
        "direction": "long",
        "entry_price": Decimal("84512.3"),
        "margin_usd": Decimal("34.66"),
        "initial_margin_usd": Decimal("34.66"),
        "leverage": Decimal("3.0"),
        "opened_at": T0,
        "closed_at": None,
        "realized_pnl_usd": None,
    }
    return Position(**(base | kw))


def test_open_message() -> None:
    text = trade_message(
        opened=True,
        paper=_paper(),
        position=_position(),
        order_price=Decimal("84512.3"),
        size=Decimal("0.0123"),
        reason="green_swing",
        stop_loss=Decimal("84089.74"),
        take_profit=Decimal("87892.79"),
        balance=Decimal("9987.12"),
        free=Decimal("9620.4"),
        open_margin=Decimal("34.66"),
        today=Decimal("12.4"),
    )
    assert text.splitlines() == [
        "[DEMO]",
        "📈 OPEN BTC 1h vwap #12",
        "long 0.0123",
        "",
        "84,512.30 · position margin $34.66 ×3 · green_swing",
        "",
        "SL 84,089.74 · TP 87,892.79",
        "",
        "🟢 balance $9,987.12 · free $9,620.40 · open margin $34.66 · today +$12.40",
    ]


def test_short_open_points_down() -> None:
    text = trade_message(
        opened=True,
        paper=_paper(),
        position=_position(direction="short", mode="live"),
        order_price=Decimal("84512.3"),
        size=Decimal("0.0123"),
        reason="below_ll_short",
        stop_loss=None,
        take_profit=None,
        balance=None,
        free=None,
        open_margin=Decimal("34.66"),
        today=Decimal("-1"),
    )
    lines = text.splitlines()
    assert lines[:3] == ["[LIVE]", "📉 OPEN BTC 1h vwap #12", "short 0.0123"]
    assert lines[-1].startswith("🔴 balance")


def test_close_message_with_pnl_and_partial() -> None:
    closed = _position(closed_at=T0, realized_pnl_usd=Decimal("-5.2"))
    text = trade_message(
        opened=False,
        paper=_paper(),
        position=closed,
        order_price=Decimal("84089.7"),
        size=Decimal("0.0123"),
        reason="stop_loss_0_5pct",
        stop_loss=None,
        take_profit=None,
        balance=Decimal("9981.92"),
        free=None,
        open_margin=Decimal("34.66"),
        today=Decimal("-5.2"),
    )
    assert text.splitlines() == [
        "[DEMO]",
        "📉 ❌ CLOSE BTC 1h vwap #12",
        "long 0.0123",
        "",
        "84,512.30 → 84,089.70 · stop_loss_0_5pct",
        "",
        "PnL -$5.20 (-15.0% of margin)",
        "",
        "🔴 balance $9,981.92 · free n/a · open margin $34.66 · today -$5.20",
    ]
    partial = _position(realized_pnl_usd=Decimal("3"))  # still open
    first = trade_message(
        opened=False,
        paper=_paper(),
        position=partial,
        order_price=Decimal("0.5123"),
        size=Decimal("1"),
        reason="manual_close",
        stop_loss=None,
        take_profit=None,
        balance=None,
        free=None,
        open_margin=Decimal("34.66"),
        today=Decimal(0),
    ).splitlines()
    assert first[1].startswith("📈 🚀 PARTIAL CLOSE") and first[6].endswith("so far")
    assert "→ 0.5123" in first[4]
    assert first[-1].startswith("🟢 balance")  # today 0


def test_prices_under_one_show_four_decimals() -> None:
    assert price(Decimal("0.235861")) == "0.2359"
    assert price(Decimal("0.5")) == "0.5000"
    assert price(Decimal("2670.9")) == "2,670.90"


def test_an_add_is_labelled_add() -> None:
    text = trade_message(
        opened=True,
        paper=_paper(),
        position=_position(),
        order_price=Decimal("83667.2"),
        size=Decimal("0.0004"),
        reason=AVERAGE_DOWN,
        stop_loss=None,
        take_profit=None,
        balance=None,
        free=None,
        open_margin=Decimal("34.66"),
        today=Decimal(0),
    )
    assert text.splitlines()[1] == "📈 ADD BTC 1h vwap #12"


def test_an_averaging_add_has_its_kind_no_sl_tp_and_short_numbers() -> None:
    paper = Paper(id=199, asset="HYPE", timeframe="15m", executor="supertrend", kind="averaging")
    text = trade_message(
        opened=True,
        paper=paper,
        position=_position(margin_usd=Decimal("100"), leverage=Decimal("10.0")),
        order_price=Decimal("78.35"),
        size=Decimal("3.190928572978451021160961925"),
        reason=AVERAGE_DOWN,
        stop_loss=None,
        take_profit=None,
        balance=Decimal("4539.37"),
        free=Decimal("4439.37"),
        open_margin=Decimal("34.66"),
        today=Decimal(0),
    )
    assert text.splitlines() == [
        "[DEMO]",
        "📈 ADD HYPE 15m supertrend averaging #199",
        "long 3.1909",
        "",
        "78.35 · position margin $100.00 ×10 · average_down",
        "",
        "🟢 balance $4,539.37 · free $4,439.37 · open margin $34.66 · today +$0.00",
    ]


def test_a_blended_leverage_shows_one_decimal_at_most() -> None:
    assert leverage(Decimal("27.96847147055546026060871264")) == "28"
    assert leverage(Decimal("12.46")) == "12.5"
    assert leverage(Decimal("10.0")) == "10"
