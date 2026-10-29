from decimal import Decimal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.execution_engine.manual_close import (
    NoOpenPosition,
    NotLive,
    OrderInFlight,
    record_closed_on_exchange,
    request_manual_close,
)

router = APIRouter()


class ClosePositionResult(BaseModel):
    decision_id: int


class ClosePosition(BaseModel):
    disable_paper: bool = True  # the paper stops once the close is placed


class ClosedOnExchange(BaseModel):
    close_price: Decimal = Field(gt=0)


@router.post("/positions/{position_id}/close", response_model=ClosePositionResult)
async def close_position(
    position_id: int, payload: ClosePosition | None = None
) -> ClosePositionResult:
    """Queues an exit request for the position - see docs/api.md."""
    disable_paper = payload is None or payload.disable_paper
    try:
        decision_id = await request_manual_close(position_id, disable_paper)
    except NoOpenPosition as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except OrderInFlight as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return ClosePositionResult(decision_id=decision_id)


@router.post("/positions/{position_id}/closed-on-exchange", status_code=204)
async def closed_on_exchange(position_id: int, payload: ClosedOnExchange) -> None:
    """Records a live position the owner already closed on Hyperliquid - see
    docs/api.md."""
    try:
        await record_closed_on_exchange(position_id, payload.close_price)
    except NoOpenPosition as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except NotLive as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except OrderInFlight as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
