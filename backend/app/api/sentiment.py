"""Market sentiment for the dashboard's header (docs/api.md)."""

from datetime import datetime

from fastapi import APIRouter
from pydantic import BaseModel

from app.sentiment.alternative_me import AlternativeMeSource
from app.sentiment.fear_greed import latest_fear_greed
from app.sentiment.redis_store import RedisFearGreedStore

router = APIRouter()
_source = AlternativeMeSource()
_store = RedisFearGreedStore()


class FearGreedOut(BaseModel):
    value: int | None  # 0 extreme fear - 100 extreme greed; null: not available
    label: str | None
    measured_at: datetime | None
    # The last value read: the source can't be read now.
    stale: bool = False


@router.get("/fear-greed", response_model=FearGreedOut)
async def fear_greed() -> FearGreedOut:
    """Never fails on the source: while it can't be read, the last value read
    (`stale`); null fields only if none ever was."""
    reading = await latest_fear_greed(_source, _store)
    if reading is None:
        return FearGreedOut(value=None, label=None, measured_at=None)
    return FearGreedOut(
        value=reading.value,
        label=reading.label,
        measured_at=reading.measured_at,
        stale=reading.stale,
    )
