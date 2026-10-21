"""Telegram bot provider. The bot token and chat id are set in the app's
settings (docs/dashboard.md#settings); without them messages are only
logged. Never raises - a failed notification must not break the caller."""

import logging

import httpx

from app.system.integration_keys import get_key

# This module's own errors are never forwarded to Telegram (see
# app/notifications/error_reporting.py) - that would loop.
logger = logging.getLogger(__name__)

# Telegram's message limit is 4096 characters.
MAX_MESSAGE_LENGTH = 4000
TIMEOUT_SECONDS = 10


async def send_telegram(text: str) -> bool:
    """Sends `text` to the configured chat. True if Telegram accepted it."""
    try:
        token = await get_key("telegram_bot_token")
        chat_id = await get_key("telegram_chat_id")
    except Exception:
        logger.exception("could not read Telegram settings, not sent: %s", text)
        return False
    if not token or not chat_id:
        logger.warning("Telegram not configured, not sent: %s", text)
        return False
    if len(text) > MAX_MESSAGE_LENGTH:
        text = text[: MAX_MESSAGE_LENGTH - 1] + "…"
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS) as client:
            response = await client.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={"chat_id": chat_id, "text": text, "disable_web_page_preview": True},
            )
            response.raise_for_status()
    except Exception:
        logger.exception("failed to send Telegram message: %s", text[:200])
        return False
    return True
