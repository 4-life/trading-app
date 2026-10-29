"""The dashboard's live auto-trading switch (docs/dashboard.md#live-cards):
whether the app may open or add to live positions on its own - executor
entries and adds. Exits (unwinds, take-profits, give-ups, maintenance-margin
closes) go through whatever it says: an open position keeps managing itself.
Demo papers ignore it.

Stored in Redis, which keeps nothing on disk (docker compose `redis`), so
it's off after every start - a restarted VPS opens nothing live until the
owner turns it back on. A missing key means off."""

from app.watchdog.redis_client import get_redis

_KEY = "live:auto_trading"


async def is_auto_open_enabled() -> bool:
    return await get_redis().get(_KEY) == "true"


async def set_auto_open_enabled(enabled: bool) -> None:
    if enabled:
        await get_redis().set(_KEY, "true")
    else:
        await get_redis().delete(_KEY)
