"""The asset universe - see docs/market-data.md#asset-universe. List, add
(any symbol - the owner knows it's the provider's), delete (not while a
paper needs it; all its market data goes with it)."""

from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import delete, select

from app.db import async_session
from app.market_data.assets import delete_asset_data, in_use
from app.market_data.models import Asset

router = APIRouter()


class AssetOut(BaseModel):
    symbol: str
    in_use: bool  # a paper needs it - can't be deleted


class AssetCreate(BaseModel):
    symbol: str = Field(min_length=1, max_length=64, pattern=r"^\S+$")


@router.get("/assets", response_model=list[AssetOut])
async def list_assets() -> list[AssetOut]:
    async with async_session() as session:
        symbols = await session.scalars(select(Asset.symbol).order_by(Asset.symbol))
        return [AssetOut(symbol=s, in_use=await in_use(session, s)) for s in symbols.all()]


@router.post("/assets", response_model=AssetOut, status_code=201)
async def add_asset(payload: AssetCreate) -> AssetOut:
    async with async_session() as session, session.begin():
        if await session.get(Asset, payload.symbol) is not None:
            raise HTTPException(status_code=409, detail=f"{payload.symbol} is already added")
        session.add(Asset(symbol=payload.symbol, created_at=datetime.now(UTC)))
        used = await in_use(session, payload.symbol)
    return AssetOut(symbol=payload.symbol, in_use=used)


@router.delete("/assets/{symbol}", status_code=204)
async def delete_asset(symbol: str) -> None:
    """The asset and all its market data - candles, trades, order books,
    funding, open interest, features."""
    async with async_session() as session, session.begin():
        if await session.get(Asset, symbol) is None:
            raise HTTPException(status_code=404, detail=f"{symbol} isn't added")
        if await in_use(session, symbol):
            raise HTTPException(status_code=409, detail=f"papers use {symbol}: delete them first")
        await session.execute(delete(Asset).where(Asset.symbol == symbol))
        await delete_asset_data(session, symbol)
