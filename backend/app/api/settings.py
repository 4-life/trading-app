"""Integration keys and the exchange API (docs/api.md#settings)."""

from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select

from app.db import async_session
from app.execution_engine.live import connect_live_client
from app.execution_engine.models import Position
from app.papers.models import Paper
from app.system.auto_open import is_auto_open_enabled
from app.system.exchange_api import (
    FIELDS,
    ExchangeApi,
    Provider,
    data_source,
    delete_exchange_api,
    get_exchange_api,
    missing_fields,
    save_exchange_api,
)
from app.system.integration_keys import EncryptionKeyMissing, masked_keys, save_keys

router = APIRouter()

KeyName = Literal["telegram_bot_token", "telegram_chat_id"]
_INTEGER_FIELDS = ("account_index", "api_key_index")


class ExchangeApiOut(BaseModel):
    provider: Provider
    keys: dict[str, str]  # masked (last 4 characters)


class SettingsOut(BaseModel):
    """Stored values, masked (last 4 characters); null = not set."""

    keys: dict[str, str | None]
    exchange_api: ExchangeApiOut | None


class SettingsUpdate(BaseModel):
    """Only the given keys change; an empty string removes a key."""

    keys: dict[KeyName, str]


class ExchangeApiIn(BaseModel):
    provider: Provider
    keys: dict[str, str]


async def _settings() -> SettingsOut:
    api = await get_exchange_api()
    exchange = None if api is None else ExchangeApiOut(provider=api.provider, keys=api.masked())
    return SettingsOut(keys=await masked_keys(), exchange_api=exchange)


async def _paper_count() -> int:
    async with async_session() as session:
        return await session.scalar(select(func.count(Paper.id))) or 0


@router.get("/settings", response_model=SettingsOut)
async def get_settings() -> SettingsOut:
    try:
        return await _settings()
    except EncryptionKeyMissing as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.put("/settings", response_model=SettingsOut)
async def update_settings(payload: SettingsUpdate) -> SettingsOut:
    try:
        await save_keys({str(name): value for name, value in payload.keys.items()})
        return await _settings()
    except EncryptionKeyMissing as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post("/settings/exchange-api", response_model=SettingsOut, status_code=201)
async def add_exchange_api(payload: ExchangeApiIn) -> SettingsOut:
    """Only one: delete the current one first. The papers' history must come
    from one provider - with papers, only an API on the current market-data
    source (Hyperliquid mainnet without an API) can be added."""
    try:
        if await get_exchange_api() is not None:
            raise HTTPException(status_code=409, detail="delete the current exchange API first")
        missing = missing_fields(payload.provider, payload.keys)
        if missing:
            raise HTTPException(status_code=422, detail=f"required: {', '.join(missing)}")
        bad = [f for f in _INTEGER_FIELDS if f in FIELDS[payload.provider]]
        bad = [f for f in bad if not payload.keys[f].strip().isdigit()]
        if bad:
            raise HTTPException(status_code=422, detail=f"must be a whole number: {', '.join(bad)}")
        keys = {name: payload.keys[name].strip() for name in FIELDS[payload.provider]}
        api = ExchangeApi(payload.provider, keys)
        if api.source != await data_source() and await _paper_count():
            raise HTTPException(
                status_code=409,
                detail="market data would switch provider - delete all papers first",
            )
        try:
            # Checks the keys with the provider before they're saved.
            await connect_live_client(api)
        except Exception as exc:
            raise HTTPException(
                status_code=422, detail=f"the provider refused the keys: {exc}"
            ) from exc
        await save_exchange_api(api)
        return await _settings()
    except EncryptionKeyMissing as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.delete("/settings/exchange-api", response_model=SettingsOut)
async def remove_exchange_api() -> SettingsOut:
    """Blocked while anything still depends on it: open live positions, live
    auto-trading on, or any paper (disable and delete them first)."""
    try:
        async with async_session() as session:
            live_open = await session.scalar(
                select(func.count(Position.id)).where(
                    Position.mode == "live", Position.closed_at.is_(None)
                )
            )
        blockers = []
        if live_open:
            blockers.append(f"close the {live_open} open live position(s)")
        if await is_auto_open_enabled():
            blockers.append("turn off live auto-trading")
        if papers := await _paper_count():
            blockers.append(f"disable and delete the {papers} paper(s)")
        if blockers:
            raise HTTPException(status_code=409, detail="first " + ", ".join(blockers))
        await delete_exchange_api()
        return await _settings()
    except EncryptionKeyMissing as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
