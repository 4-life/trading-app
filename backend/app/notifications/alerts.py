import logging
import re
from datetime import UTC, datetime
from typing import Literal

from app.db import async_session
from app.notifications.telegram import send_telegram
from app.system import deploy
from app.system.models import SystemEvent

logger = logging.getLogger(__name__)

Level = Literal["info", "warning", "error", "critical"]
EMOJI: dict[Level, str] = {"info": "ℹ️", "warning": "⚠️", "error": "❌", "critical": "🚨"}
_URL_QUERY = re.compile(r"(https?://[^\s'\"?]+)\?[^\s'\"]*")
# What a key or token looks like: a bearer token, a Telegram bot token, hex
# (private keys, 40+ digits) and any other run of 40+ base64 characters.
_SECRETS = re.compile(
    r"Bearer\s+\S+"
    r"|\d{6,}:[A-Za-z0-9_-]{30,}"  # also inside .../bot<token>/...
    r"|\b(?:0x)?[0-9a-fA-F]{40,}\b"
    r"|[A-Za-z0-9+/_-]{40,}={0,2}"
)


def redact(text: str) -> str:
    """Drops URL query strings - they can carry account ids - and anything
    shaped like a key or token (an exchange SDK's error might quote one)."""
    return _SECRETS.sub("[redacted]", _URL_QUERY.sub(r"\1?…", text))


async def alert(source: str, level: Level, message: str) -> None:
    """Records a system event, then notifies the owner via Telegram
    (docs/watchdog.md#alerting) - not during a deploy (app/system/deploy.py),
    except the deploy's own messages. Never raises."""
    try:
        async with async_session() as session:
            session.add(
                SystemEvent(
                    occurred_at=datetime.now(UTC), source=source, level=level, detail=message
                )
            )
            await session.commit()
    except Exception:
        # The database may be the thing that's down - still notify.
        logger.exception("could not record system event: %s", message[:200])
    if source != deploy.SOURCE and await deploy.quiet():
        return
    # Telegram is a third party: no URL query strings (docs/watchdog.md#alerting).
    await send_telegram(f"{EMOJI[level]} {level.upper()} [{source}]: {redact(message)}")
