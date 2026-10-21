import asyncio
import logging
from collections.abc import Callable, Coroutine
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, cast

from hyperliquid.info import Info
from hyperliquid.utils.error import ClientError
from requests.adapters import HTTPAdapter

from app.config import settings
from app.exchange.base import (
    Balance,
    ExchangeAdapter,
    MarketData,
    Order,
    OrderSide,
    Position,
)

WsCallback = Callable[[dict[str, Any]], Coroutine[Any, Any, None]]

logger = logging.getLogger(__name__)

# get_market_data is called by several services every pass (execution,
# risk, watchdog) - a light retry budget on HTTP 429, since several calls in
# one pass would compound a longer one.
_RATE_LIMIT_MAX_RETRIES = 2
_RATE_LIMIT_RETRY_DELAY_SECONDS = 3.0

# requests keeps 10 connections per host by default; the candle poll runs
# every (asset, interval) concurrently via asyncio.to_thread, whose default
# executor tops out at 32 threads - beyond 10 connections were discarded.
_HTTP_POOL_SIZE = 32

# connect() runs once per service at startup, when many services hit the
# API at once; a failure kills one-shot services like `backfill`, which
# blocks the whole startup chain - so it gets a more patient retry budget.
_CONNECT_RATE_LIMIT_MAX_RETRIES = 5
_CONNECT_RATE_LIMIT_RETRY_DELAY_SECONDS = 5.0


class HyperliquidAdapter(ExchangeAdapter):
    """Hyperliquid market data (REST + WebSocket). Account/order methods
    need signing with the API key from the app's settings - live execution
    isn't implemented yet (docs/execution-engine.md#live-execution). Demo
    orders are filled by the execution engine in the database."""

    def __init__(self, base_url: str) -> None:
        self._base_url = base_url
        self._info: Info | None = None

    async def connect(self, *, skip_ws: bool = False) -> None:
        # Idempotent. skip_ws is only honored on the first connect.
        if self._info is not None:
            return

        # No timeout here used to mean requests could hang indefinitely on a
        # network hiccup or a slow/rate-limited response - a single stuck
        # call could block a whole sequential backfill for hours. skip_ws
        # lets one-shot callers (e.g. the backfill script) skip starting the
        # WebSocket manager thread they'll never use.
        for attempt in range(_CONNECT_RATE_LIMIT_MAX_RETRIES + 1):
            try:
                self._info = await asyncio.to_thread(
                    Info,
                    self._base_url,
                    skip_ws=skip_ws,
                    timeout=settings.exchange_request_timeout_seconds,
                )
                self.info.session.mount("https://", HTTPAdapter(pool_maxsize=_HTTP_POOL_SIZE))
                return
            except ClientError as e:
                if e.status_code != 429 or attempt == _CONNECT_RATE_LIMIT_MAX_RETRIES:
                    raise
                logger.warning(
                    "rate limited (429) connecting to Hyperliquid, retrying in %.0fs "
                    "(attempt %d/%d)",
                    _CONNECT_RATE_LIMIT_RETRY_DELAY_SECONDS,
                    attempt + 1,
                    _CONNECT_RATE_LIMIT_MAX_RETRIES,
                )
                await asyncio.sleep(_CONNECT_RATE_LIMIT_RETRY_DELAY_SECONDS)

    @property
    def info(self) -> Info:
        if self._info is None:
            raise RuntimeError("call connect() before using HyperliquidAdapter")
        return self._info

    async def reconnect_ws(self) -> None:
        """The SDK's WebsocketManager doesn't auto-reconnect once the
        underlying socket drops (observed: a "Connection reset by peer"
        silently stops every trade/book message forever, with nothing
        raised anywhere but a log line) - and its stop() is one-shot, the
        manager can't be restarted in place (its ping thread, like any
        Python thread, can only be started once). So this throws away the
        whole Info object and connects fresh; callers must re-subscribe
        afterward, since the new one starts with zero subscriptions."""
        if self._info is not None:
            await asyncio.to_thread(self._info.disconnect_websocket)
            # connect() is idempotent on a non-None self._info (see its own
            # docstring) - without clearing it first, the call below would
            # just no-op against the now-disconnected instance instead of
            # actually reconnecting.
            self._info = None
        await self.connect()

    async def _l2_snapshot_with_retry(self, asset: str) -> dict[str, Any]:
        for attempt in range(_RATE_LIMIT_MAX_RETRIES + 1):
            try:
                return await asyncio.to_thread(self.info.l2_snapshot, asset)
            except ClientError as e:
                if e.status_code != 429 or attempt == _RATE_LIMIT_MAX_RETRIES:
                    raise
                logger.warning(
                    "%s: rate limited (429) fetching l2 snapshot, retrying in %.0fs "
                    "(attempt %d/%d)",
                    asset,
                    _RATE_LIMIT_RETRY_DELAY_SECONDS,
                    attempt + 1,
                    _RATE_LIMIT_MAX_RETRIES,
                )
                await asyncio.sleep(_RATE_LIMIT_RETRY_DELAY_SECONDS)
        raise AssertionError("unreachable - loop above always returns or raises")

    def is_listed(self, asset: str) -> bool:
        return asset in self.info.name_to_coin

    async def get_market_data(self, asset: str) -> MarketData:
        book = await self._l2_snapshot_with_retry(asset)
        levels = book["levels"]
        best_bid = Decimal(levels[0][0]["px"])
        best_ask = Decimal(levels[1][0]["px"])
        return MarketData(
            asset=asset,
            bid=best_bid,
            ask=best_ask,
            last=(best_bid + best_ask) / 2,
            timestamp=datetime.fromtimestamp(book["time"] / 1000, tz=UTC),
        )

    async def get_l2_snapshot(self, asset: str) -> dict[str, Any]:
        return await self._l2_snapshot_with_retry(asset)

    async def get_candles(
        self, asset: str, interval: str, start_time_ms: int, end_time_ms: int
    ) -> list[dict[str, Any]]:
        return await asyncio.to_thread(
            self.info.candles_snapshot, asset, interval, start_time_ms, end_time_ms
        )

    async def get_funding_history(
        self, asset: str, start_time_ms: int, end_time_ms: int | None = None
    ) -> list[dict[str, Any]]:
        return await asyncio.to_thread(self.info.funding_history, asset, start_time_ms, end_time_ms)

    async def get_asset_contexts(self) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        meta, asset_ctxs = await asyncio.to_thread(self.info.meta_and_asset_ctxs)
        return meta, asset_ctxs

    async def margin_limits(self) -> dict[str, tuple[Decimal, Decimal]]:
        """Each perpetual's maxLeverage; Hyperliquid's maintenance margin is
        half the initial margin at it."""
        meta = await asyncio.to_thread(self.info.meta)
        return {
            u["name"]: (Decimal(u["maxLeverage"]), 1 / (2 * Decimal(u["maxLeverage"])))
            for u in meta["universe"]
            if u.get("maxLeverage")
        }

    async def get_user_fills(self, address: str) -> list[dict[str, Any]]:
        return await asyncio.to_thread(self.info.user_fills, address)

    async def get_user_state(self, address: str) -> dict[str, Any]:
        return await asyncio.to_thread(self.info.user_state, address)

    def subscribe_trades(self, asset: str, on_message: WsCallback) -> int:
        return self._subscribe({"type": "trades", "coin": asset}, on_message)

    def subscribe_l2_book(self, asset: str, on_message: WsCallback) -> int:
        return self._subscribe({"type": "l2Book", "coin": asset}, on_message)

    def _subscribe(self, subscription: dict[str, Any], on_message: WsCallback) -> int:
        loop = asyncio.get_running_loop()

        def callback(ws_msg: dict[str, Any]) -> None:
            asyncio.run_coroutine_threadsafe(on_message(ws_msg), loop)

        return cast(int, self.info.subscribe(subscription, callback))

    # -- Account/order methods: need a signing key, not wired up yet. --

    async def get_balances(self) -> list[Balance]:
        raise NotImplementedError(
            "live execution is not implemented (requires signing with the API key)"
        )

    async def get_positions(self) -> list[Position]:
        raise NotImplementedError(
            "live execution is not implemented (requires signing with the API key)"
        )

    async def get_open_orders(self) -> list[Order]:
        raise NotImplementedError(
            "live execution is not implemented (requires signing with the API key)"
        )

    async def place_order(
        self, asset: str, side: OrderSide, size: Decimal, price: Decimal | None = None
    ) -> Order:
        raise NotImplementedError(
            "live execution is not implemented (requires signing with the API key)"
        )

    async def cancel_order(self, order_id: str) -> None:
        raise NotImplementedError(
            "live execution is not implemented (requires signing with the API key)"
        )

    async def modify_order(
        self, order_id: str, size: Decimal | None = None, price: Decimal | None = None
    ) -> Order:
        raise NotImplementedError(
            "live execution is not implemented (requires signing with the API key)"
        )

    async def get_order(self, order_id: str) -> Order:
        raise NotImplementedError(
            "live execution is not implemented (requires signing with the API key)"
        )
