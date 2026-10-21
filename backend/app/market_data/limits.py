"""Each perpetual's margin limits from the selected provider (its max
leverage and maintenance margin) - stored by the market-data service on
start, read by the API (a paper's leverage) and the averaging backtest -
see docs/market-data.md#market-limits."""

import logging
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.db import async_session
from app.exchange.base import MarketAdapter
from app.market_data.models import MarketLimit
from app.system.exchange_api import data_source

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Limits:
    max_leverage: float
    maintenance_margin: float  # the share of the notional the exchange liquidates under


async def refresh_market_limits(provider: str, adapter: MarketAdapter) -> None:
    """Stores the provider's limits of every listed perpetual."""
    limits = await adapter.margin_limits()
    if not limits:
        return
    now = datetime.now(UTC)
    rows = [
        {
            "provider": provider,
            "asset": asset,
            "max_leverage": max_leverage,
            "maintenance_margin": maintenance,
            "updated_at": now,
        }
        for asset, (max_leverage, maintenance) in limits.items()
    ]
    stmt = pg_insert(MarketLimit).values(rows)
    stmt = stmt.on_conflict_do_update(
        index_elements=["provider", "asset"],
        set_={
            "max_leverage": stmt.excluded.max_leverage,
            "maintenance_margin": stmt.excluded.maintenance_margin,
            "updated_at": now,
        },
    )
    async with async_session() as session:
        await session.execute(stmt)
        await session.commit()
    logger.info("%s: margin limits of %d markets stored", provider, len(rows))


async def all_market_limits() -> dict[str, Limits]:
    """Every stored asset's limits at the selected provider."""
    provider = (await data_source()).provider
    async with async_session() as session:
        rows = await session.execute(
            select(
                MarketLimit.asset, MarketLimit.max_leverage, MarketLimit.maintenance_margin
            ).where(MarketLimit.provider == provider)
        )
    return {asset: Limits(float(m), float(mm)) for asset, m, mm in rows.all()}


async def market_limits(asset: str) -> Limits | None:
    """The selected provider's limits for `asset`; None until market data
    stored them (or for a market it doesn't list)."""
    provider = (await data_source()).provider
    async with async_session() as session:
        row = await session.get(MarketLimit, (provider, asset))
    if row is None:
        return None
    return Limits(float(row.max_leverage), float(row.maintenance_margin))
