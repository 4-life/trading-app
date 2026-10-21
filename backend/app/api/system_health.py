from fastapi import APIRouter
from pydantic import BaseModel

from app.watchdog.redis_client import get_last_check_results, is_kill_switch_active

router = APIRouter()


class CheckResultOut(BaseModel):
    name: str
    ok: bool
    detail: str


class SystemHealth(BaseModel):
    checked_at: str | None
    kill_switch_active: bool
    healthy: bool
    checks: list[CheckResultOut]


@router.get("/system-health", response_model=SystemHealth)
async def system_health() -> SystemHealth:
    payload = await get_last_check_results()
    kill_switch_active = await is_kill_switch_active()

    if payload is None:
        # watchdog hasn't completed a check pass yet (just started, or isn't
        # running) - distinct from "unhealthy": there's simply no data yet.
        return SystemHealth(
            checked_at=None, kill_switch_active=kill_switch_active, healthy=False, checks=[]
        )

    checks = [CheckResultOut(**c) for c in payload["results"]]
    return SystemHealth(
        checked_at=payload["checked_at"],
        kill_switch_active=kill_switch_active,
        healthy=all(c.ok for c in checks),
        checks=checks,
    )
