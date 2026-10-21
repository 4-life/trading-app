"""Live trading on Lighter (docs/execution-engine.md#live-execution): orders
signed with an API key of the account (account index + API key index), by
the lighter-sdk SignerClient (a bundled native signer).

A market order only returns once it's submitted - the fill is read back
from the account's trades, matched by the order's client index. Standard
Lighter accounts pay no trading fees."""

import asyncio
import time
from decimal import ROUND_DOWN, ROUND_UP, Decimal
from typing import Any

from app.config import settings
from app.exchange.lighter import LighterAdapter, UnknownMarket
from app.execution_engine.live import LiveAccount, LiveFill, LiveOrderError, LivePosition

FILL_WAIT_SECONDS = 15.0
FILL_POLL_SECONDS = 2.0  # REST is scarce on Lighter (app/exchange/lighter.py)


def scaled(value: Decimal, decimals: int, rounding: str = ROUND_DOWN) -> int:
    """Lighter's integer amounts / prices: `value` x 10^decimals."""
    return int((value * Decimal(10) ** decimals).to_integral_value(rounding=rounding))


def average_fill(trades: list[dict[str, Any]], client_index: int, account_index: int) -> LiveFill:
    """The order's fill from its trades (the ones where this account's side
    carries `client_index`) - LiveOrderError if there are none."""
    size, notional = Decimal(0), Decimal(0)
    for t in trades:
        ours = (
            int(t.get("bid_client_id") or -1) == client_index
            and int(t.get("bid_account_id") or -1) == account_index
        ) or (
            int(t.get("ask_client_id") or -1) == client_index
            and int(t.get("ask_account_id") or -1) == account_index
        )
        if ours:
            size += Decimal(t["size"])
            notional += Decimal(t["size"]) * Decimal(t["price"])
    if size == 0:
        raise LiveOrderError("rejected by provider: order not filled")
    return LiveFill(order_id=client_index, price=notional / size, size=size)


def _check_sent(what: str, response: Any, error: str | None) -> None:
    """A signing error, or a transaction the exchange answered with a non-200 code."""
    code = getattr(response, "code", 200)
    if error or code != 200:
        detail = error or getattr(response, "message", None) or f"code {code}"
        raise LiveOrderError(f"rejected by provider: {what}: {detail}")


class LighterLiveClient:
    def __init__(self, signer: Any, markets: LighterAdapter, account_index: int) -> None:
        self._signer = signer
        self._markets = markets
        self._account_index = account_index

    @classmethod
    async def create(
        cls, base_url: str, private_key: str, account_index: int, api_key_index: int
    ) -> LighterLiveClient:
        from lighter.signer_client import SignerClient  # loads the native signer

        # Built on the event loop (it opens an aiohttp session); only the key
        # check - a blocking native call over the network - runs in a thread.
        signer = SignerClient(
            url=base_url, account_index=account_index, api_private_keys={api_key_index: private_key}
        )
        error = await asyncio.to_thread(signer.check_client)
        if error:
            await signer.close()  # type: ignore[no-untyped-call]
            raise LiveOrderError(f"rejected by provider: Lighter API key check failed: {error}")
        markets = LighterAdapter(base_url, budget="live")  # never waits behind market data
        await markets.connect()
        return cls(signer, markets, account_index)

    def _market(self, asset: str) -> dict[str, Any]:
        try:
            return self._markets.market(asset)
        except UnknownMarket as exc:
            raise LiveOrderError(f"rejected by provider: {exc.args[0]}") from None

    async def _account(self) -> dict[str, Any]:
        data = await self._markets.get_json("account", by="index", value=self._account_index)
        accounts = data.get("accounts") or []
        if not accounts:
            raise LiveOrderError(f"Lighter account {self._account_index} not found")
        account: dict[str, Any] = accounts[0]
        return account

    async def account(self) -> LiveAccount:
        a = await self._account()
        return LiveAccount(
            account_value=Decimal(str(a.get("total_asset_value") or a["collateral"])),
            withdrawable=Decimal(str(a["available_balance"])),
        )

    async def positions(self) -> list[LivePosition]:
        out: list[LivePosition] = []
        for p in (await self._account()).get("positions") or []:
            size = Decimal(str(p["position"])) * int(p["sign"])
            if size == 0:
                continue
            out.append(
                LivePosition(
                    asset=p["symbol"],
                    size=size,
                    entry_price=Decimal(str(p["avg_entry_price"])),
                    unrealized_pnl=Decimal(str(p["unrealized_pnl"])),
                )
            )
        return out

    async def mid_price(self, asset: str) -> Decimal:
        self._market(asset)
        return (await self._markets.get_market_data(asset)).last

    def size_decimals(self, asset: str) -> int:
        return int(self._market(asset)["size_decimals"])

    async def open(self, asset: str, is_buy: bool, size: Decimal, leverage: int) -> LiveFill:
        market = self._market(asset)
        _, response, error = await self._signer.update_leverage(
            int(market["market_id"]), self._signer.ISOLATED_MARGIN_MODE, leverage
        )
        _check_sent("leverage update failed", response, error)
        return await self._market_order(market, is_buy, size, reduce_only=False)

    async def close(self, asset: str, is_buy: bool, size: Decimal) -> LiveFill:
        return await self._market_order(self._market(asset), is_buy, size, reduce_only=True)

    async def add(self, asset: str, is_buy: bool, size: Decimal) -> LiveFill:
        return await self._market_order(self._market(asset), is_buy, size, reduce_only=False)

    async def add_margin(self, asset: str, amount_usd: Decimal) -> None:
        _, response, error = await self._signer.update_margin(
            int(self._market(asset)["market_id"]),
            float(amount_usd),
            self._signer.ISOLATED_MARGIN_ADD_COLLATERAL,
        )
        _check_sent("margin transfer failed", response, error)

    async def _market_order(
        self, market: dict[str, Any], is_buy: bool, size: Decimal, *, reduce_only: bool
    ) -> LiveFill:
        asset, market_id = market["symbol"], int(market["market_id"])
        mid = await self.mid_price(asset)
        slippage = Decimal(str(settings.live_slippage_pct))
        # The worst average price accepted - beyond it the order doesn't fill.
        worst = mid * (1 + slippage) if is_buy else mid * (1 - slippage)
        client_index = time.time_ns() // 1_000_000 % (2**47)  # unique per order
        _, response, error = await self._signer.create_market_order(
            market_index=market_id,
            client_order_index=client_index,
            base_amount=scaled(size, int(market["size_decimals"])),
            avg_execution_price=scaled(
                worst, int(market["price_decimals"]), ROUND_UP if is_buy else ROUND_DOWN
            ),
            is_ask=not is_buy,
            reduce_only=reduce_only,
        )
        _check_sent("order refused", response, error)
        deadline = time.monotonic() + FILL_WAIT_SECONDS
        while True:
            await asyncio.sleep(FILL_POLL_SECONDS)
            data = await self._markets.get_json(
                "trades",
                account_index=self._account_index,
                market_id=market_id,
                sort_by="timestamp",
                limit=50,
            )
            try:
                return average_fill(data.get("trades") or [], client_index, self._account_index)
            except LiveOrderError:
                if time.monotonic() >= deadline:
                    raise

    async def fee(self, fill: LiveFill) -> Decimal:
        return Decimal(0)
