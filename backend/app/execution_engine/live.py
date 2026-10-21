"""Live trading (docs/execution-engine.md#live-execution) on the exchange
API selected in the app's settings (app/system/exchange_api.py) - its
provider, on mainnet. LiveClient is what the engine uses; this module has
the Hyperliquid client, app/execution_engine/live_lighter.py the Lighter one.

Hyperliquid orders are signed by the API (agent) wallet whose private key is
stored; it trades on behalf of the main account (the account address) and
can't withdraw. The main wallet's key never touches the server.

Market orders are capped at LIVE_SLIPPAGE_PCT from the mid price; positions
use isolated margin at the paper's leverage."""

import asyncio
from dataclasses import dataclass
from decimal import ROUND_DOWN, Decimal
from typing import Any, Protocol

from eth_account import Account
from hyperliquid.exchange import Exchange
from hyperliquid.info import Info

from app.config import settings
from app.system.exchange_api import TAKER_FEE_RATES, ExchangeApi, get_exchange_api


class LiveOrderError(Exception):
    """The exchange refused or didn't fill the order."""


@dataclass(frozen=True)
class LiveFill:
    order_id: int
    price: Decimal
    size: Decimal


@dataclass(frozen=True)
class LivePosition:
    asset: str
    size: Decimal  # signed: > 0 long, < 0 short
    entry_price: Decimal
    unrealized_pnl: Decimal


@dataclass(frozen=True)
class LiveAccount:
    account_value: Decimal
    withdrawable: Decimal


def parse_order_response(response: Any) -> LiveFill:
    """Hyperliquid order response -> the fill, or LiveOrderError."""
    if not isinstance(response, dict) or response.get("status") != "ok":
        raise LiveOrderError(f"order rejected: {response}")
    statuses = response["response"]["data"]["statuses"]
    status = statuses[0] if statuses else {}
    if "filled" in status:
        filled = status["filled"]
        return LiveFill(
            order_id=int(filled["oid"]),
            price=Decimal(str(filled["avgPx"])),
            size=Decimal(str(filled["totalSz"])),
        )
    if "error" in status:
        raise LiveOrderError(str(status["error"]))
    raise LiveOrderError(f"order not filled: {status}")


def round_size(size: Decimal, sz_decimals: int) -> Decimal:
    """Down to the asset's size step - never more than the budget allows."""
    return size.quantize(Decimal(1).scaleb(-sz_decimals), rounding=ROUND_DOWN)


class LiveClient(Protocol):
    async def account(self) -> LiveAccount: ...

    async def positions(self) -> list[LivePosition]: ...

    async def mid_price(self, asset: str) -> Decimal: ...

    def size_decimals(self, asset: str) -> int:
        """LiveOrderError for an asset the provider doesn't list."""
        ...

    async def open(self, asset: str, is_buy: bool, size: Decimal, leverage: int) -> LiveFill:
        """Sets isolated leverage, then a market order."""
        ...

    async def close(self, asset: str, is_buy: bool, size: Decimal) -> LiveFill: ...

    async def add(self, asset: str, is_buy: bool, size: Decimal) -> LiveFill:
        """A market order growing the open isolated position - its leverage
        setting is left as it is."""
        ...

    async def add_margin(self, asset: str, amount_usd: Decimal) -> None:
        """Moves `amount_usd` of collateral into the asset's isolated position."""
        ...

    async def fee(self, fill: LiveFill) -> Decimal:
        """The fee charged for the order."""
        ...


class HyperliquidLiveClient:
    def __init__(self, base_url: str, private_key: str, account_address: str) -> None:
        self.address = account_address
        # A request timeout, so a stalled connection can't block a service forever.
        timeout = settings.exchange_request_timeout_seconds
        self._info = Info(base_url, skip_ws=True, timeout=timeout)
        self._exchange = Exchange(
            Account.from_key(private_key),
            base_url,
            account_address=account_address,
            timeout=timeout,
        )

    async def account(self) -> LiveAccount:
        state = await asyncio.to_thread(self._info.user_state, self.address)
        return LiveAccount(
            account_value=Decimal(str(state["marginSummary"]["accountValue"])),
            withdrawable=Decimal(str(state["withdrawable"])),
        )

    async def positions(self) -> list[LivePosition]:
        state = await asyncio.to_thread(self._info.user_state, self.address)
        out: list[LivePosition] = []
        for item in state["assetPositions"]:
            p = item["position"]
            if Decimal(str(p["szi"])) == 0:
                continue
            out.append(
                LivePosition(
                    asset=p["coin"],
                    size=Decimal(str(p["szi"])),
                    entry_price=Decimal(str(p["entryPx"])),
                    unrealized_pnl=Decimal(str(p["unrealizedPnl"])),
                )
            )
        return out

    async def mid_price(self, asset: str) -> Decimal:
        mids = await asyncio.to_thread(self._info.all_mids)
        if asset not in mids:
            raise LiveOrderError(f"{asset} isn't listed on Hyperliquid")
        return Decimal(str(mids[asset]))

    def size_decimals(self, asset: str) -> int:
        try:
            return int(self._info.asset_to_sz_decimals[self._info.name_to_asset(asset)])
        except KeyError:
            raise LiveOrderError(f"{asset} isn't listed on Hyperliquid") from None

    async def open(self, asset: str, is_buy: bool, size: Decimal, leverage: int) -> LiveFill:
        """Sets isolated leverage, then a market (IOC) order."""
        response = await asyncio.to_thread(self._exchange.update_leverage, leverage, asset, False)
        if not isinstance(response, dict) or response.get("status") != "ok":
            raise LiveOrderError(f"leverage update rejected: {response}")
        return await self._market(asset, is_buy, size)

    async def close(self, asset: str, is_buy: bool, size: Decimal) -> LiveFill:
        return await self._market(asset, is_buy, size)

    async def add(self, asset: str, is_buy: bool, size: Decimal) -> LiveFill:
        return await self._market(asset, is_buy, size)

    async def add_margin(self, asset: str, amount_usd: Decimal) -> None:
        response = await asyncio.to_thread(
            self._exchange.update_isolated_margin, float(amount_usd), asset
        )
        if not isinstance(response, dict) or response.get("status") != "ok":
            raise LiveOrderError(f"margin transfer rejected: {response}")

    async def _market(self, asset: str, is_buy: bool, size: Decimal) -> LiveFill:
        response = await asyncio.to_thread(
            self._exchange.market_open,
            asset,
            is_buy,
            float(size),
            None,
            settings.live_slippage_pct,
        )
        return parse_order_response(response)

    async def fee(self, fill: LiveFill) -> Decimal:
        """The fee Hyperliquid charged for the order; the taker-fee estimate
        if the fill isn't listed yet."""
        fills = await asyncio.to_thread(self._info.user_fills, self.address)
        fees = [Decimal(str(f["fee"])) for f in fills if int(f.get("oid", -1)) == fill.order_id]
        estimate = fill.price * fill.size * TAKER_FEE_RATES["hyperliquid"]
        return sum(fees, Decimal(0)) if fees else estimate


async def _connect(api: ExchangeApi) -> LiveClient:
    keys = api.keys
    if api.provider == "lighter":
        from app.execution_engine.live_lighter import LighterLiveClient

        return await LighterLiveClient.create(
            api.source.url,
            keys["api_key_private_key"],
            int(keys["account_index"]),
            int(keys["api_key_index"]),
        )
    return await asyncio.to_thread(
        HyperliquidLiveClient,
        api.source.url,
        keys["api_wallet_private_key"],
        keys["account_address"],
    )


_cached: tuple[ExchangeApi, LiveClient] | None = None


async def connect_live_client(api: ExchangeApi) -> None:
    """Connects with `api`'s keys (raises if the provider refuses them) and
    keeps the client for live_client() in this process."""
    global _cached
    _cached = (api, await _connect(api))


async def live_client() -> LiveClient | None:
    """None without an exchange API. The client (which loads exchange
    metadata) is reused until the API changes."""
    global _cached
    api = await get_exchange_api()
    if api is None:
        return None
    if _cached is None or _cached[0] != api:
        _cached = (api, await _connect(api))
    return _cached[1]
