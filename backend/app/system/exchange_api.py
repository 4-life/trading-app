"""The exchange API selected in the dashboard's settings (docs/dashboard.md#exchange-api):
at most one - a provider (Hyperliquid or Lighter) and its keys, stored
encrypted as one setting. Mainnet only: the provider places live orders
(real money) and supplies all market data; without one, market data comes
from Hyperliquid (demo only). Testing is demo mode on real prices."""

import json
import logging
from dataclasses import dataclass
from decimal import Decimal
from typing import Literal, get_args

from sqlalchemy import delete

from app.db import async_session
from app.execution_engine.models import EquitySnapshot
from app.system.integration_keys import get_key, mask, save_keys

logger = logging.getLogger(__name__)

Provider = Literal["hyperliquid", "lighter"]
PROVIDERS: tuple[Provider, ...] = get_args(Provider)

# The keys each provider needs (all required).
FIELDS: dict[Provider, tuple[str, ...]] = {
    # An API (agent) wallet: trades for the main account, can't withdraw.
    "hyperliquid": ("api_wallet_private_key", "account_address"),
    "lighter": ("api_key_private_key", "account_index", "api_key_index"),
}

# Perp taker fee (VIP 0) - market orders only, so always taker. Lighter charges none.
TAKER_FEE_RATES: dict[Provider, Decimal] = {
    "hyperliquid": Decimal("0.00045"),
    "lighter": Decimal(0),
}
# Perp maker fee (VIP 0) - the backtests assume limit orders that fill.
MAKER_FEE_RATES: dict[Provider, Decimal] = {
    "hyperliquid": Decimal("0.00015"),
    "lighter": Decimal(0),
}

URLS: dict[Provider, str] = {
    "hyperliquid": "https://api.hyperliquid.xyz",
    "lighter": "https://mainnet.zklighter.elliot.ai",
}

_SETTING = "exchange_api"


@dataclass(frozen=True)
class DataSource:
    """Where market data (and live orders) come from."""

    provider: Provider

    @property
    def url(self) -> str:
        return URLS[self.provider]


DEFAULT_SOURCE = DataSource("hyperliquid")


@dataclass(frozen=True)
class ExchangeApi:
    provider: Provider
    keys: dict[str, str]

    @property
    def source(self) -> DataSource:
        return DataSource(self.provider)

    def masked(self) -> dict[str, str]:
        return {name: mask(value) for name, value in self.keys.items()}


def missing_fields(provider: Provider, keys: dict[str, str]) -> list[str]:
    return [name for name in FIELDS[provider] if not keys.get(name, "").strip()]


async def get_exchange_api() -> ExchangeApi | None:
    raw = await get_key(_SETTING)
    if raw is None:
        return None
    data = json.loads(raw)
    if data.get("network", "mainnet") != "mainnet":
        # Saved before testnet support was dropped - its keys don't work on mainnet.
        logger.warning("the stored %s testnet API is ignored - add a mainnet one", data["provider"])
        return None
    return ExchangeApi(data["provider"], data["keys"])


async def _reset_live_equity() -> None:
    """A new (or no) exchange account: the live equity history - the risk
    engine's peak for its drawdown kill switch and its day start - belonged
    to the old one. Without this, a smaller new account would read as a deep
    drawdown and block every live entry for good."""
    async with async_session() as session, session.begin():
        await session.execute(delete(EquitySnapshot).where(EquitySnapshot.mode == "live"))


async def save_exchange_api(api: ExchangeApi) -> None:
    keys = {name: api.keys[name].strip() for name in FIELDS[api.provider]}
    value = json.dumps({"provider": api.provider, "keys": keys})
    await save_keys({_SETTING: value})
    await _reset_live_equity()


async def delete_exchange_api() -> None:
    await save_keys({_SETTING: ""})
    await _reset_live_equity()


async def data_source() -> DataSource:
    api = await get_exchange_api()
    return api.source if api is not None else DEFAULT_SOURCE


async def taker_fee_rate() -> Decimal:
    """The selected provider's taker fee rate (Hyperliquid without one)."""
    return TAKER_FEE_RATES[(await data_source()).provider]


async def maker_fee_rate() -> Decimal:
    """The selected provider's maker fee rate (Hyperliquid without one)."""
    return MAKER_FEE_RATES[(await data_source()).provider]
