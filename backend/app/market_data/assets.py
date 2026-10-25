"""The asset universe (docs/market-data.md#asset-universe): the perpetuals
collected live, added and deleted in the dashboard's assets editor. An asset
a paper uses can't be deleted; deleting one removes all its market data."""

from sqlalchemy import delete, exists, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import async_session
from app.feature_engine.models import Feature
from app.market_data.models import (
    Asset,
    Candle,
    FundingRate,
    OpenInterestSnapshot,
    OrderBookSnapshot,
    Trade,
)
from app.papers.models import REGIME_ASSET, Paper

# Every table keyed by asset that holds its market data.
_DATA = (Candle, Trade, OrderBookSnapshot, FundingRate, OpenInterestSnapshot, Feature)


async def configured_assets() -> list[str]:
    async with async_session() as session:
        return list(await session.scalars(select(Asset.symbol).order_by(Asset.symbol)))


async def probe_asset() -> str:
    """An asset to ask the provider about (the watchdog's connectivity check)."""
    return next(iter(await configured_assets()), REGIME_ASSET)


async def in_use(session: AsyncSession, asset: str) -> bool:
    """A paper needs the asset's data: its own papers (scanners' too), trend
    papers (the bear-market filter reads REGIME_ASSET)."""
    uses = [Paper.asset == asset]
    if asset == REGIME_ASSET:
        uses.append(Paper.executor == "trend")
    return bool(await session.scalar(select(exists().where(or_(*uses)))))


async def delete_asset_data(session: AsyncSession, asset: str) -> None:
    for model in _DATA:
        await session.execute(delete(model).where(model.asset == asset))
