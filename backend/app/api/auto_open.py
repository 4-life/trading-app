from fastapi import APIRouter
from pydantic import BaseModel

from app.system.auto_open import is_auto_open_enabled, set_auto_open_enabled

router = APIRouter()


class AutoOpenState(BaseModel):
    enabled: bool


@router.get("/auto-open", response_model=AutoOpenState)
async def get_auto_open() -> AutoOpenState:
    return AutoOpenState(enabled=await is_auto_open_enabled())


@router.post("/auto-open", response_model=AutoOpenState)
async def update_auto_open(payload: AutoOpenState) -> AutoOpenState:
    await set_auto_open_enabled(payload.enabled)
    return payload
