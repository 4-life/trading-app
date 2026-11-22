"""FearGreedSource adapter: alternative.me's public Fear & Greed index API."""

from datetime import UTC, datetime
from typing import Any

import httpx

from app.sentiment.fear_greed import FearGreed

URL = "https://api.alternative.me/fng/"
TIMEOUT_SECONDS = 5.0


def parse(body: Any) -> FearGreed:
    """The API's answer -> the latest reading (ValueError on another shape)."""
    try:
        latest = body["data"][0]
        return FearGreed(
            value=int(latest["value"]),
            label=str(latest["value_classification"]),
            measured_at=datetime.fromtimestamp(int(latest["timestamp"]), UTC),
        )
    except (KeyError, IndexError, TypeError) as exc:
        raise ValueError(f"unexpected fear & greed answer: {body!r}"[:300]) from exc


class AlternativeMeSource:
    async def latest(self) -> FearGreed:
        async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS) as client:
            response = await client.get(URL, params={"limit": 1})
            response.raise_for_status()
            return parse(response.json())
