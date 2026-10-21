import json
import time
from datetime import UTC, datetime
from typing import Any

from redis.asyncio import Redis

from app.config import settings
from app.watchdog.results import CheckResult

KILL_SWITCH_KEY = "watchdog:kill_switch"
LAST_CHECK_KEY = "watchdog:last_check"

_redis: Redis | None = None


def get_redis() -> Redis:
    global _redis
    if _redis is None:
        _redis = Redis(host=settings.redis_host, port=settings.redis_port, decode_responses=True)
    return _redis


async def set_kill_switch(active: bool, reason: str = "") -> None:
    """While set, executors open no new positions - see
    docs/watchdog.md#kill-switch."""
    r = get_redis()
    if active:
        await r.set(KILL_SWITCH_KEY, reason)
    else:
        await r.delete(KILL_SWITCH_KEY)


async def is_kill_switch_active() -> bool:
    r = get_redis()
    return bool(await r.exists(KILL_SWITCH_KEY))


async def set_last_check_results(results: list[CheckResult]) -> None:
    """Watchdog only logged/alerted before this - nothing could see the
    actual check results without reading container logs. This is the
    snapshot the dashboard's health stat reads."""
    payload = {
        "checked_at": datetime.now(UTC).isoformat(),
        "results": [{"name": r.name, "ok": r.ok, "detail": r.detail} for r in results],
    }
    await get_redis().set(LAST_CHECK_KEY, json.dumps(payload))


async def get_last_check_results() -> dict[str, Any] | None:
    raw = await get_redis().get(LAST_CHECK_KEY)
    if raw is None:
        return None
    payload: dict[str, Any] = json.loads(raw)
    return payload


_HEARTBEAT_KEY = "heartbeat:{}"


async def set_heartbeat(service: str) -> None:
    """Called by a service at the start of every pass."""
    await get_redis().set(_HEARTBEAT_KEY.format(service), str(time.time()))


async def heartbeat_age_seconds(service: str) -> float | None:
    """Seconds since the service's last pass; None if it never ran."""
    raw = await get_redis().get(_HEARTBEAT_KEY.format(service))
    return time.time() - float(raw) if raw is not None else None
