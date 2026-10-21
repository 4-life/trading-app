"""Deploy-aware alerting (docs/watchdog.md#deploys).

The deploy script runs `python -m app.system.deploy start` before it
restarts the stack and `... finish` after. In between, and for SETTLE_SECONDS
after the finish, alerts are recorded but not sent to Telegram - services
restarting aren't news. Then the watchdog sends one summary: all checks
passing, or what's failing. A deploy that never finishes stops the quiet
after MAX_SECONDS, and the watchdog says so.

The marker is a plain row in `settings` (Postgres survives the restarts)."""

import asyncio
import json
import sys
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.db import async_session
from app.system.models import Setting

SOURCE = "deploy"
SETTLE_SECONDS = 150  # after the finish: services catch up before the summary
MAX_SECONDS = 30 * 60  # a deploy still "running" after this is reported as stuck
_KEY = "deploy"


@dataclass(frozen=True)
class Deploy:
    started_at: datetime
    finished_at: datetime | None

    def quiet(self, now: datetime) -> bool:
        """Alerts held back: running (not stuck), or just finished."""
        if self.finished_at is None:
            return now - self.started_at < timedelta(seconds=MAX_SECONDS)
        return now - self.finished_at < timedelta(seconds=SETTLE_SECONDS)

    def due(self, now: datetime) -> bool:
        """Time for the watchdog's summary: settled after the finish, or stuck."""
        return not self.quiet(now)


async def current() -> Deploy | None:
    async with async_session() as session:
        row = await session.get(Setting, _KEY)
    if row is None:
        return None
    data = json.loads(row.value)
    finished = data.get("finished_at")
    return Deploy(
        datetime.fromisoformat(data["started_at"]),
        datetime.fromisoformat(finished) if finished else None,
    )


async def _save(deploy: Deploy) -> None:
    value = json.dumps(
        {
            "started_at": deploy.started_at.isoformat(),
            "finished_at": deploy.finished_at.isoformat() if deploy.finished_at else None,
        }
    )
    now = datetime.now(UTC)
    stmt = pg_insert(Setting).values(key=_KEY, value=value, encrypted=False, updated_at=now)
    stmt = stmt.on_conflict_do_update(
        index_elements=["key"], set_={"value": value, "updated_at": now}
    )
    async with async_session() as session:
        await session.execute(stmt)
        await session.commit()


async def clear() -> None:
    async with async_session() as session:
        await session.execute(delete(Setting).where(Setting.key == _KEY))
        await session.commit()


async def quiet() -> bool:
    """Never raises - the database may be what's down; then alerts go out."""
    try:
        deploy = await current()
    except Exception:
        return False
    return deploy is not None and deploy.quiet(datetime.now(UTC))


async def start() -> None:
    from app.notifications.alerts import alert

    await _save(Deploy(datetime.now(UTC), None))
    await alert(SOURCE, "info", "deploy started - alerts paused until it's done")


async def finish() -> None:
    deploy = await current()
    if deploy is None:
        return
    await _save(Deploy(deploy.started_at, datetime.now(UTC)))


def main() -> None:
    command = sys.argv[1] if len(sys.argv) > 1 else ""
    if command not in ("start", "finish"):
        sys.exit("usage: python -m app.system.deploy start|finish")
    asyncio.run(start() if command == "start" else finish())


if __name__ == "__main__":
    main()
