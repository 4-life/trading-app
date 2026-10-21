"""Lighter market data - docs/market-data.md#providers.

Lighter allows a standard account only 60 REST requests per minute per IP,
for every service on the server together, and blocks the IP (HTTP 405)
past it. So live data comes over one WebSocket per process (`_Stream`,
opened on first use): trades, the order book (a snapshot, then incremental
updates kept here), candles (cached - recent windows are served from it)
and market stats (best bid / ask). REST is only for history and metadata,
through a budget shared by all services (a Redis counter per minute), with
a pause when Lighter signals a limit - the live trading client's calls
(account, fills) through a separate one, so they never queue behind them.

Everything comes out in Hyperliquid's shapes (candles, funding, asset
contexts, trade / l2Book messages), so the collector, the backfill and the
scanner work the same whatever the provider."""

import asyncio
import contextlib
import json
import logging
import time
from collections.abc import Awaitable, Callable, Coroutine
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Literal

import httpx
import websockets

from app.config import settings
from app.exchange.base import MarketData
from app.exchange.hyperliquid import WsCallback
from app.feature_engine.engine import INTERVAL_MINUTES
from app.watchdog.redis_client import get_redis

logger = logging.getLogger(__name__)

PAGE = 500  # candles / funding rows per request - Lighter's cap
# Below Lighter's 60 / minute / IP together. Each budget is its own Redis
# counter: the live trading client's account / fill calls never wait for a
# scanner pass or a backfill to free up the data budget.
REST_PER_MINUTE = 45  # market data: history, metadata, quotes
LIVE_REST_PER_MINUTE = 10  # the live trading client
Budget = Literal["data", "live"]
LIMITED_PAUSE_SECONDS = 60  # after Lighter signals a limit
_RETRIES = 10  # a limit pause is 60 s: waits out a block up to ~10 min, so no chunk is lost
BOOK_EMIT_SECONDS = 5.0  # an order-book snapshot (l2Book message) per asset this often
BOOK_DEPTH = 20  # levels per side in a snapshot
STATS_MAX_AGE_SECONDS = 30  # older market stats -> a REST quote instead
PING_SECONDS = 60  # Lighter closes a connection silent for 2 minutes
RECONNECT_SECONDS = 5.0
CANDLES_KEPT = 10  # per (asset, interval) in the cache
_HOUR_MS = 3_600_000


class UnknownMarket(KeyError):
    """The asset isn't a listed, active Lighter perpetual."""


def funding_fraction(rate: str, direction: str) -> Decimal:
    """Lighter's hourly rate is in percent and unsigned, with the paying
    side in `direction`; Hyperliquid's is a signed fraction (> 0: longs pay)."""
    fraction = Decimal(rate) / 100
    return fraction if direction == "long" else -fraction


def rate_limited(response: httpx.Response) -> bool:
    """Lighter's limit answers: 429, 405 (IP blocked), 403 (bot check) or
    400 with code 23000 ("Too Many Requests!")."""
    if response.status_code in (403, 405, 429):
        return True
    return response.status_code == 400 and '"code":23000' in response.text.replace(" ", "")


def hl_candle(c: dict[str, Any]) -> dict[str, Any]:
    return {k: (int(c[k]) if k == "t" else str(c[k])) for k in ("t", "o", "h", "l", "c", "v")}


def apply_book_update(side: dict[str, str], levels: list[dict[str, Any]]) -> None:
    """Incremental order-book update: size 0 removes the level."""
    for level in levels:
        if Decimal(level["size"]) == 0:
            side.pop(level["price"], None)
        else:
            side[level["price"]] = level["size"]


def top_levels(side: dict[str, str], descending: bool) -> list[dict[str, Any]]:
    prices = sorted(side, key=Decimal, reverse=descending)[:BOOK_DEPTH]
    return [{"px": p, "sz": side[p], "n": 1} for p in prices]


async def _rest_slot(budget: Budget = "data") -> None:
    """Waits for a slot in this minute's `budget`, shared by all services."""
    limit = REST_PER_MINUTE if budget == "data" else LIVE_REST_PER_MINUTE
    while True:
        minute = int(time.time() // 60)
        key = f"lighter:rest:{minute}" if budget == "data" else f"lighter:rest:live:{minute}"
        redis = get_redis()
        used = await redis.incr(key)
        if used == 1:
            await redis.expire(key, 120)
        if used <= limit:
            return
        await asyncio.sleep((minute + 1) * 60 - time.time() + 0.1)


class _Stream:
    """One WebSocket connection: subscribes to channels (again after a
    reconnect), keeps it alive, hands every message to `on_message`."""

    def __init__(self, url: str, on_message: Callable[[dict[str, Any]], Awaitable[None]]) -> None:
        self._url = url
        self._on_message = on_message
        self._channels: set[str] = set()
        self._ws: Any = None
        self._task: asyncio.Task[None] | None = None

    async def subscribe(self, channel: str) -> None:
        if self._task is None:
            self._task = asyncio.get_running_loop().create_task(self._run())
        if channel in self._channels:
            return
        self._channels.add(channel)
        if self._ws is not None:
            with contextlib.suppress(Exception):
                await self._ws.send(json.dumps({"type": "subscribe", "channel": channel}))

    @property
    def connected(self) -> bool:
        return self._ws is not None

    async def restart(self) -> None:
        if self._ws is not None:
            with contextlib.suppress(Exception):
                await self._ws.close()

    async def _run(self) -> None:
        while True:
            try:
                async with websockets.connect(self._url, max_size=None) as ws:
                    self._ws = ws
                    for channel in sorted(self._channels):
                        await ws.send(json.dumps({"type": "subscribe", "channel": channel}))
                    pinger = asyncio.get_running_loop().create_task(self._ping(ws))
                    try:
                        async for raw in ws:
                            try:
                                await self._on_message(json.loads(raw))
                            except Exception:
                                logger.exception("lighter: bad stream message")
                    finally:
                        pinger.cancel()
            except Exception as exc:
                logger.warning("lighter stream: %s - reconnecting", exc)
            self._ws = None
            await asyncio.sleep(RECONNECT_SECONDS)

    async def _ping(self, ws: Any) -> None:
        while True:
            await asyncio.sleep(PING_SECONDS)
            await ws.send(json.dumps({"type": "ping"}))


def lighter_margin_limits(details: dict[str, Any]) -> tuple[Decimal, Decimal]:
    """A market's (max leverage, maintenance margin of the notional) from its
    margin fractions, in basis points: min_initial_margin_fraction 200 = 2%
    = 50x, maintenance_margin_fraction 120 = 1.2%."""
    basis = Decimal(10_000)
    return (
        basis / Decimal(details["min_initial_margin_fraction"]),
        Decimal(details["maintenance_margin_fraction"]) / basis,
    )


class LighterAdapter:
    def __init__(self, base_url: str, budget: Budget = "data") -> None:
        """`budget`: the REST budget its calls count against (`_rest_slot`)."""
        self._api = f"{base_url}/api/v1"
        self._budget: Budget = budget
        self._client: httpx.AsyncClient | None = None
        # symbol -> market details (orderBookDetails), active perpetuals only
        self._markets: dict[str, dict[str, Any]] = {}
        self._symbols: dict[int, str] = {}  # market id -> symbol
        self._stream = _Stream(base_url.replace("https://", "wss://") + "/stream", self._dispatch)
        self._stats: dict[str, tuple[float, dict[str, Any]]] = {}  # symbol -> (at, stats)
        self._books: dict[str, tuple[dict[str, str], dict[str, str]]] = {}  # (bids, asks)
        self._candles: dict[tuple[str, str], dict[int, dict[str, Any]]] = {}
        self._trade_callbacks: dict[str, WsCallback] = {}
        self._book_callbacks: dict[str, WsCallback] = {}
        self._book_task: asyncio.Task[None] | None = None

    async def connect(self, *, skip_ws: bool = False) -> None:
        """Idempotent. The stream opens on first use, whatever `skip_ws`."""
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=settings.exchange_request_timeout_seconds)
            await self._load_markets()

    async def get_json(self, path: str, **params: Any) -> dict[str, Any]:
        """A REST call within the shared budget; pauses when Lighter signals a limit."""
        assert self._client is not None, "connect() first"
        for attempt in range(_RETRIES + 1):
            await _rest_slot(self._budget)
            response = await self._client.get(f"{self._api}/{path}", params=params)
            limited = rate_limited(response)
            if (limited or response.status_code >= 500) and attempt < _RETRIES:
                pause = LIMITED_PAUSE_SECONDS if limited else 5.0
                logger.warning(
                    "lighter %s: HTTP %d%s - retrying in %.0fs",
                    path,
                    response.status_code,
                    " (rate limited)" if limited else "",
                    pause,
                )
                await asyncio.sleep(pause)
                continue
            response.raise_for_status()
            data: dict[str, Any] = response.json()
            return data
        raise AssertionError("unreachable - the loop returns or raises")

    async def _load_markets(self) -> list[dict[str, Any]]:
        details = (await self.get_json("orderBookDetails")).get("order_book_details") or []
        active = [
            d for d in details if d.get("market_type") == "perp" and d.get("status") == "active"
        ]
        self._markets = {d["symbol"]: d for d in active}
        self._symbols = {int(d["market_id"]): d["symbol"] for d in active}
        return active

    def is_listed(self, asset: str) -> bool:
        return asset in self._markets

    def market(self, asset: str) -> dict[str, Any]:
        try:
            return self._markets[asset]
        except KeyError:
            raise UnknownMarket(f"{asset} isn't listed on Lighter") from None

    def market_id(self, asset: str) -> int:
        return int(self.market(asset)["market_id"])

    async def margin_limits(self) -> dict[str, tuple[Decimal, Decimal]]:
        return {
            symbol: lighter_margin_limits(details)
            for symbol, details in self._markets.items()
            if details.get("min_initial_margin_fraction")
        }

    # --- stream ---

    async def _dispatch(self, msg: dict[str, Any]) -> None:
        kind = str(msg.get("type", ""))
        name, _, rest = str(msg.get("channel", "")).partition(":")
        if name == "market_stats":
            stats = msg.get("market_stats") or {}
            symbol = self._symbols.get(int(stats.get("market_id", -1)))
            if symbol:
                self._stats[symbol] = (time.monotonic(), stats)
        elif name == "candle":
            market, _, interval = rest.partition(":")
            symbol = self._symbols.get(int(market))
            if symbol:
                cache = self._candles.setdefault((symbol, interval), {})
                for c in msg.get("candles") or []:
                    cache[int(c["t"])] = hl_candle(c)
                for t in sorted(cache)[:-CANDLES_KEPT]:
                    del cache[t]
        elif name == "order_book":
            symbol = self._symbols.get(int(rest))
            book = msg.get("order_book") or {}
            if symbol:
                if kind.startswith("subscribed"):
                    self._books[symbol] = ({}, {})
                bids, asks = self._books.setdefault(symbol, ({}, {}))
                apply_book_update(bids, book.get("bids") or [])
                apply_book_update(asks, book.get("asks") or [])
        elif name == "trade" and kind.startswith("update"):
            symbol = self._symbols.get(int(rest))
            callback = self._trade_callbacks.get(symbol or "")
            trades = msg.get("trades") or []
            if symbol and callback and trades:
                data = [
                    {
                        "coin": symbol,
                        # Hyperliquid: B = the taker bought, A = sold.
                        "side": "B" if t.get("is_maker_ask") else "A",
                        "px": t["price"],
                        "sz": t["size"],
                        "time": int(t["timestamp"]),
                    }
                    for t in trades
                ]
                await callback({"channel": "trades", "data": data})

    async def _emit_books(self) -> None:
        while True:
            await asyncio.sleep(BOOK_EMIT_SECONDS)
            now_ms = int(datetime.now(UTC).timestamp() * 1000)
            if not self._stream.connected:
                continue  # a stale book isn't market data
            for symbol, callback in list(self._book_callbacks.items()):
                bids, asks = self._books.get(symbol, ({}, {}))
                if not bids or not asks:
                    continue
                levels = [top_levels(bids, True), top_levels(asks, False)]
                data = {"coin": symbol, "time": now_ms, "levels": levels}
                try:
                    await callback({"channel": "l2Book", "data": data})
                except Exception:
                    logger.exception("lighter %s: order-book snapshot failed", symbol)

    # --- MarketAdapter ---

    async def get_market_data(self, asset: str) -> MarketData:
        """Best bid / ask from the market-stats stream; REST until it's fresh."""
        await self._stream.subscribe(f"market_stats/{self.market_id(asset)}")
        at, stats = self._stats.get(asset, (0.0, {}))
        if time.monotonic() - at <= STATS_MAX_AGE_SECONDS and stats.get("best_bid_price"):
            bid, ask = Decimal(stats["best_bid_price"]), Decimal(stats["best_ask_price"])
        else:
            book = await self.get_json("orderBookOrders", market_id=self.market_id(asset), limit=1)
            bid, ask = Decimal(book["bids"][0]["price"]), Decimal(book["asks"][0]["price"])
        return MarketData(
            asset=asset, bid=bid, ask=ask, last=(bid + ask) / 2, timestamp=datetime.now(UTC)
        )

    async def get_candles(
        self, asset: str, interval: str, start_time_ms: int, end_time_ms: int
    ) -> list[dict[str, Any]]:
        """A recent window comes from the candle stream once its cache covers
        it; history (and the first call) from REST."""
        step_ms = INTERVAL_MINUTES[interval] * 60_000
        await self._stream.subscribe(f"candle/{self.market_id(asset)}/{interval}")
        # Only a window ending now (the live poll) - never history (a backfill).
        recent = end_time_ms >= time.time() * 1000 - 2 * step_ms
        cached = self._candles.get((asset, interval), {})
        covered = cached and min(cached) <= start_time_ms // step_ms * step_ms
        if recent and covered and self._stream.connected:
            return [cached[t] for t in sorted(cached) if start_time_ms <= t <= end_time_ms]
        by_time: dict[int, dict[str, Any]] = {}
        start = start_time_ms
        while start < end_time_ms:
            end = min(start + PAGE * step_ms, end_time_ms)
            data = await self.get_json(
                "candles",
                market_id=self.market_id(asset),
                resolution=interval,
                start_timestamp=start,
                end_timestamp=end,
                count_back=PAGE,
            )
            for c in data.get("c") or []:
                if start_time_ms <= int(c["t"]) <= end_time_ms:
                    by_time[int(c["t"])] = hl_candle(c)
            start = end
        if recent:  # seed the cache, so the next live window comes from it
            cache = self._candles.setdefault((asset, interval), {})
            for t, c in by_time.items():
                if t >= end_time_ms - CANDLES_KEPT * step_ms:
                    cache[t] = c
        return [by_time[t] for t in sorted(by_time)]

    async def get_funding_history(
        self, asset: str, start_time_ms: int, end_time_ms: int | None = None
    ) -> list[dict[str, Any]]:
        """Lighter settles funding hourly: a window inside one hour has none
        new, so it costs no request."""
        end_ms = end_time_ms if end_time_ms is not None else int(time.time() * 1000)
        if end_ms // _HOUR_MS == start_time_ms // _HOUR_MS:
            return []
        by_time: dict[int, dict[str, Any]] = {}
        start = start_time_ms
        while start < end_ms:
            end = min(start + PAGE * _HOUR_MS, end_ms)
            data = await self.get_json(
                "fundings",
                market_id=self.market_id(asset),
                resolution="1h",
                start_timestamp=start // 1000,
                end_timestamp=end // 1000,
                count_back=PAGE,
            )
            for f in data.get("fundings") or []:
                time_ms = int(f["timestamp"]) * 1000
                if start_time_ms <= time_ms <= end_ms:
                    rate = funding_fraction(f["rate"], f["direction"])
                    by_time[time_ms] = {"time": time_ms, "fundingRate": str(rate), "premium": "0"}
            start = end
        return [by_time[t] for t in sorted(by_time)]

    async def get_asset_contexts(self) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        """Hyperliquid's (meta, asset contexts): the names, 24h notional
        volume and open interest of every active perpetual."""
        markets = await self._load_markets()
        meta = {"universe": [{"name": m["symbol"]} for m in markets]}
        contexts = [
            {
                "dayNtlVlm": str(m.get("daily_quote_token_volume") or 0),
                "openInterest": str(m.get("open_interest") or 0),
            }
            for m in markets
        ]
        return meta, contexts

    def subscribe_trades(self, asset: str, on_message: WsCallback) -> int:
        self._trade_callbacks[asset] = on_message
        self._spawn(self._stream.subscribe(f"trade/{self.market_id(asset)}"))
        return len(self._trade_callbacks)

    def subscribe_l2_book(self, asset: str, on_message: WsCallback) -> int:
        self._book_callbacks[asset] = on_message
        self._spawn(self._stream.subscribe(f"order_book/{self.market_id(asset)}"))
        if self._book_task is None:
            self._book_task = asyncio.get_running_loop().create_task(self._emit_books())
        return len(self._book_callbacks)

    def _spawn(self, coro: Coroutine[Any, Any, None]) -> None:
        asyncio.get_running_loop().create_task(coro)

    async def reconnect_ws(self) -> None:
        """Reconnects the stream; it subscribes to every channel again itself."""
        await self._stream.restart()
