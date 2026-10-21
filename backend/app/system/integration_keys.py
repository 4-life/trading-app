"""Integration keys entered in the dashboard's settings modal, stored
encrypted (Fernet, SETTINGS_ENCRYPTION_KEY) in the `settings` table - see
docs/dashboard.md#settings."""

from datetime import UTC, datetime

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.config import settings
from app.db import async_session
from app.system.models import Setting

# The exchange API is stored separately (app/system/exchange_api.py).
KEYS = (
    "telegram_bot_token",
    "telegram_chat_id",
)


class EncryptionKeyMissing(Exception):
    pass


def _fernet() -> Fernet:
    if not settings.settings_encryption_key:
        raise EncryptionKeyMissing("SETTINGS_ENCRYPTION_KEY is not set")
    try:
        return Fernet(settings.settings_encryption_key.encode())
    except ValueError as exc:
        raise EncryptionKeyMissing(
            "SETTINGS_ENCRYPTION_KEY is not a valid Fernet key (32 url-safe base64-encoded bytes)"
        ) from exc


def _decrypt(fernet: Fernet, value: str) -> str:
    try:
        return fernet.decrypt(value.encode()).decode()
    except InvalidToken as exc:
        raise EncryptionKeyMissing(
            "stored keys can't be decrypted with SETTINGS_ENCRYPTION_KEY - was it changed?"
        ) from exc


def mask(value: str) -> str:
    """Shows only the last 4 characters."""
    return "•" * 8 + value[-4:] if len(value) > 4 else "•" * 8


async def get_key(name: str) -> str | None:
    async with async_session() as session:
        row = await session.get(Setting, name)
    if row is None:
        return None
    return _decrypt(_fernet(), row.value)


async def masked_keys() -> dict[str, str | None]:
    async with async_session() as session:
        rows = (await session.scalars(select(Setting).where(Setting.key.in_(KEYS)))).all()
    fernet = _fernet() if rows else None
    stored = {r.key: mask(_decrypt(fernet, r.value)) for r in rows if fernet}
    return {name: stored.get(name) for name in KEYS}


async def save_keys(values: dict[str, str]) -> None:
    """An empty string removes the key."""
    fernet = _fernet()
    now = datetime.now(UTC)
    async with async_session() as session:
        for name, value in values.items():
            if not value:
                await session.execute(delete(Setting).where(Setting.key == name))
                continue
            encrypted = fernet.encrypt(value.encode()).decode()
            stmt = pg_insert(Setting).values(
                key=name, value=encrypted, encrypted=True, updated_at=now
            )
            stmt = stmt.on_conflict_do_update(
                index_elements=["key"], set_={"value": encrypted, "updated_at": now}
            )
            await session.execute(stmt)
        await session.commit()
