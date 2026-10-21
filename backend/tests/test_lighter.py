"""Pure unit tests, no database or network."""

from decimal import Decimal

import httpx
import pytest

from app.exchange import lighter
from app.exchange.lighter import (
    LighterAdapter,
    apply_book_update,
    funding_fraction,
    rate_limited,
    top_levels,
)
from app.execution_engine.live import LiveOrderError
from app.execution_engine.live_lighter import average_fill, scaled


def test_funding_is_a_signed_fraction() -> None:
    assert funding_fraction("0.0009", "long") == Decimal("0.000009")
    assert funding_fraction("0.0009", "short") == Decimal("-0.000009")


def test_scaled_amounts_and_prices() -> None:
    assert scaled(Decimal("0.123456"), 5) == 12345  # sizes round down
    assert scaled(Decimal("84546.71"), 1) == 845467
    assert scaled(Decimal("84546.71"), 1, "ROUND_UP") == 845468


def test_average_fill_from_this_accounts_trades() -> None:
    trades = [
        {"bid_client_id": 7, "bid_account_id": 1, "size": "1", "price": "100"},
        {"bid_client_id": 7, "bid_account_id": 1, "size": "3", "price": "104"},
        {"bid_client_id": 7, "bid_account_id": 2, "size": "5", "price": "90"},  # another account
        {"ask_client_id": 8, "ask_account_id": 1, "size": "5", "price": "90"},  # another order
    ]
    fill = average_fill(trades, 7, 1)
    assert (fill.order_id, fill.size, fill.price) == (7, Decimal(4), Decimal(103))
    sold = average_fill(trades, 8, 1)
    assert (sold.size, sold.price) == (Decimal(5), Decimal(90))


def test_no_trades_means_not_filled() -> None:
    with pytest.raises(LiveOrderError, match="rejected by provider"):
        average_fill([], 7, 1)


def test_rate_limit_answers() -> None:
    def response(status: int, body: str = "{}") -> httpx.Response:
        return httpx.Response(status, text=body)

    assert rate_limited(response(429)) and rate_limited(response(405))
    assert rate_limited(response(400, '{"code": 23000, "message": "Too Many Requests!"}'))
    assert not rate_limited(response(400, '{"code": 20001}')) and not rate_limited(response(200))


def test_order_book_updates_and_top_levels() -> None:
    bids: dict[str, str] = {}
    apply_book_update(bids, [{"price": "99", "size": "1"}, {"price": "100", "size": "2"}])
    apply_book_update(bids, [{"price": "99", "size": "0"}, {"price": "98", "size": "3"}])
    assert bids == {"100": "2", "98": "3"}
    assert [lvl["px"] for lvl in top_levels(bids, descending=True)] == ["100", "98"]


async def test_stream_messages_feed_the_caches_and_callbacks() -> None:
    adapter = LighterAdapter("https://example.invalid")
    adapter._symbols = {1: "BTC"}
    got: list[dict[str, object]] = []

    async def on_trade(msg: dict[str, object]) -> None:
        got.append(msg)

    adapter._trade_callbacks["BTC"] = on_trade
    await adapter._dispatch(
        {
            "type": "subscribed/order_book",
            "channel": "order_book:1",
            "order_book": {
                "bids": [{"price": "10", "size": "1"}],
                "asks": [{"price": "11", "size": "2"}],
            },
        }
    )
    await adapter._dispatch(
        {
            "type": "update/order_book",
            "channel": "order_book:1",
            "order_book": {
                "bids": [{"price": "10", "size": "0"}, {"price": "9", "size": "4"}],
                "asks": [],
            },
        }
    )
    assert adapter._books["BTC"] == ({"9": "4"}, {"11": "2"})
    candle = {"t": 60_000, "o": 1.5, "h": 2, "l": 1, "c": 1.75, "v": 3}
    await adapter._dispatch(
        {"type": "update/candle", "channel": "candle:1:1m", "candles": [candle]}
    )
    assert adapter._candles[("BTC", "1m")][60_000]["c"] == "1.75"
    trade = {"price": "10.5", "size": "0.1", "timestamp": 1, "is_maker_ask": True}
    await adapter._dispatch({"type": "update/trade", "channel": "trade:1", "trades": [trade]})
    assert got[0]["data"] == [{"coin": "BTC", "side": "B", "px": "10.5", "sz": "0.1", "time": 1}]


async def test_history_windows_never_come_from_or_seed_the_cache() -> None:
    """A backfill fetches old windows one after another - each must hit REST."""
    adapter = LighterAdapter("https://example.invalid")
    adapter._markets = {"BTC": {"symbol": "BTC", "market_id": 1}}
    adapter._symbols = {1: "BTC"}
    calls: list[int] = []
    hour = 3_600_000

    async def fake_get_json(path: str, **params: object) -> dict[str, object]:
        start = int(params["start_timestamp"])  # type: ignore[call-overload]
        calls.append(start)
        candles = [
            {"t": start + i * hour, "o": 1, "h": 1, "l": 1, "c": 1, "v": 1} for i in range(3)
        ]
        return {"c": candles}

    async def no_stream(channel: str) -> None:
        return None

    adapter.get_json = fake_get_json  # type: ignore[method-assign]
    adapter._stream.subscribe = no_stream  # type: ignore[method-assign]
    adapter._stream._ws = object()  # "connected" - the cache would be used if allowed
    base = 1_700_000_000_000 // hour * hour  # 2023 - long past
    first = await adapter.get_candles("BTC", "1h", base, base + 3 * hour)
    second = await adapter.get_candles("BTC", "1h", base + hour, base + 4 * hour)
    assert len(first) == 3 and len(second) == 3
    assert calls == [base, base + hour]
    assert ("BTC", "1h") not in adapter._candles


class _FakeRedis:
    """incr / expire only - a per-key counter."""

    def __init__(self) -> None:
        self.counts: dict[str, int] = {}

    async def incr(self, key: str) -> int:
        self.counts[key] = self.counts.get(key, 0) + 1
        return self.counts[key]

    async def expire(self, key: str, seconds: int) -> None:
        return None


async def test_the_live_budget_is_counted_apart_from_market_data(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    redis = _FakeRedis()
    monkeypatch.setattr(lighter, "get_redis", lambda: redis)
    monkeypatch.setattr("app.exchange.lighter.time.time", lambda: 120.0)  # minute 2
    for _ in range(lighter.REST_PER_MINUTE):
        await lighter._rest_slot()  # the data budget used up...
    await lighter._rest_slot("live")  # ...a live call still goes through at once
    assert redis.counts == {"lighter:rest:2": lighter.REST_PER_MINUTE, "lighter:rest:live:2": 1}
