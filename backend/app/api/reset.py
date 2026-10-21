from fastapi import APIRouter
from pydantic import BaseModel

from app.execution_engine.reset import reset_demo_state

router = APIRouter()


class ResetResult(BaseModel):
    positions_deleted: int
    orders_deleted: int
    decisions_deleted: int


@router.post("/reset", response_model=ResetResult)
async def reset() -> ResetResult:
    """Demo reset - see docs/papers.md#demo-reset. Never touches live."""
    return ResetResult(**await reset_demo_state())
