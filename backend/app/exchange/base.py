from abc import ABC, abstractmethod
from collections.abc import Callable, Coroutine
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any, Protocol

from pydantic import BaseModel


class OrderSide(StrEnum):
    BUY = "buy"
    SELL = "sell"


class OrderStatus(StrEnum):
    OPEN = "open"
    FILLED = "filled"
    PARTIALLY_FILLED = "partially_filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"


class Balance(BaseModel):
    asset: str
    total: Decimal
    available: Decimal


class Position(BaseModel):
    asset: str
    side: OrderSide
    size: Decimal
    entry_price: Decimal
    unrealized_pnl: Decimal
    opened_at: datetime
    # Most favorable price since entry.
    peak_price: Decimal
    # The price unrealized_pnl was computed against.
    current_price: Decimal


class Order(BaseModel):
    order_id: str
    asset: str
    side: OrderSide
    size: Decimal
    price: Decimal | None
    status: OrderStatus


class MarketData(BaseModel):
    asset: str
    bid: Decimal
    ask: Decimal
    last: Decimal
    timestamp: datetime


class ExchangeAdapter(ABC):
    @abstractmethod
    async def connect(self) -> None: ...

    @abstractmethod
    async def get_balances(self) -> list[Balance]: ...

    @abstractmethod
    async def get_positions(self) -> list[Position]: ...

    @abstractmethod
    async def get_open_orders(self) -> list[Order]: ...

    @abstractmethod
    async def get_market_data(self, asset: str) -> MarketData: ...

    @abstractmethod
    async def place_order(
        self, asset: str, side: OrderSide, size: Decimal, price: Decimal | None = None
    ) -> Order: ...

    @abstractmethod
    async def cancel_order(self, order_id: str) -> None: ...

    @abstractmethod
    async def modify_order(
        self, order_id: str, size: Decimal | None = None, price: Decimal | None = None
    ) -> Order: ...

    @abstractmethod
    async def get_order(self, order_id: str) -> Order: ...


class MarketAdapter(Protocol):
    """Market data, whichever provider (app/exchange/source.py) - in
    Hyperliquid's shapes: HyperliquidAdapter, LighterAdapter."""

    async def connect(self, *, skip_ws: bool = False) -> None: ...

    def is_listed(self, asset: str) -> bool:
        """A perpetual the provider trades (after connect())."""
        ...

    async def reconnect_ws(self) -> None: ...

    async def get_market_data(self, asset: str) -> MarketData: ...

    async def get_candles(
        self, asset: str, interval: str, start_time_ms: int, end_time_ms: int
    ) -> list[dict[str, Any]]: ...

    async def get_funding_history(
        self, asset: str, start_time_ms: int, end_time_ms: int | None = None
    ) -> list[dict[str, Any]]: ...

    async def get_asset_contexts(self) -> tuple[dict[str, Any], list[dict[str, Any]]]: ...

    async def margin_limits(self) -> dict[str, tuple[Decimal, Decimal]]:
        """Per listed perpetual: (the most leverage a position may take, the
        maintenance margin - the share of the notional the exchange
        liquidates under)."""
        ...

    def subscribe_trades(
        self, asset: str, on_message: Callable[[dict[str, Any]], Coroutine[Any, Any, None]]
    ) -> int: ...

    def subscribe_l2_book(
        self, asset: str, on_message: Callable[[dict[str, Any]], Coroutine[Any, Any, None]]
    ) -> int: ...
