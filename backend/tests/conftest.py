from collections.abc import AsyncGenerator

import pytest

from app.db import engine
from app.watchdog.redis_client import get_redis


@pytest.fixture(scope="session", autouse=True)
async def _close_shared_connections() -> AsyncGenerator[None]:
    """app/db.py's engine and app/watchdog/redis_client's Redis client are
    both process-lifetime singletons, same as in every real service - never
    explicitly closed there because the container just gets stopped. A test
    run has no such stop signal, so leaving these open after the last test
    means dangling pooled connections until the interpreter itself exits."""
    yield
    await engine.dispose()
    await get_redis().aclose()
