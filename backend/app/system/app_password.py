"""The app password (docs/api.md#authentication): APP_PASSWORD from the
environment until the owner changes it in the dashboard - then its scrypt
hash in `settings` (PASSWORD_KEY), which takes over. Removing that row (SQL)
brings APP_PASSWORD back."""

import base64
import hashlib
import hmac
import os
from datetime import UTC, datetime

from app.config import settings
from app.db import async_session
from app.system.models import Setting

PASSWORD_KEY = "app_password_hash"
MIN_LENGTH = 8
# scrypt's cost (n, r, p) - ~16 MB and a few tens of ms per check.
_N, _R, _P = 2**14, 8, 1


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode()


def hash_password(password: str, salt: bytes | None = None) -> str:
    """The stored form: scrypt$<salt>$<hash>, both base64."""
    salt = salt or os.urandom(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=_N, r=_R, p=_P)
    return f"scrypt${_b64(salt)}${_b64(digest)}"


def verify_hash(password: str, stored: str) -> bool:
    scheme, _, rest = stored.partition("$")
    salt, _, _ = rest.partition("$")
    if scheme != "scrypt" or not salt:
        return False
    expected = hash_password(password, base64.urlsafe_b64decode(salt))
    return hmac.compare_digest(expected.encode(), stored.encode())


async def stored_hash() -> str | None:
    async with async_session() as session:
        row = await session.get(Setting, PASSWORD_KEY)
    return row.value if row is not None else None


async def secret() -> str:
    """What the login tokens are signed with: the stored hash, else
    APP_PASSWORD - a new password logs every token out. "" = none set."""
    return await stored_hash() or settings.app_password


async def password_matches(password: str) -> bool:
    stored = await stored_hash()
    if stored is not None:
        return verify_hash(password, stored)
    current = settings.app_password
    return bool(current) and hmac.compare_digest(password.encode(), current.encode())


async def save_password(password: str) -> None:
    now = datetime.now(UTC)
    async with async_session() as session, session.begin():
        row = await session.get(Setting, PASSWORD_KEY)
        if row is None:
            session.add(Setting(key=PASSWORD_KEY, value=hash_password(password), updated_at=now))
        else:
            row.value, row.encrypted, row.updated_at = hash_password(password), False, now
