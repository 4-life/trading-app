"""FearGreedStore adapter: the last Fear & Greed reading in Redis."""

import json
from datetime import datetime

from app.sentiment.fear_greed import FearGreed
from app.watchdog.redis_client import get_redis

KEY = "sentiment:fear_greed"


class RedisFearGreedStore:
    async def save(self, reading: FearGreed) -> None:
        payload = {
            "value": reading.value,
            "label": reading.label,
            "measured_at": reading.measured_at.isoformat(),
        }
        await get_redis().set(KEY, json.dumps(payload))

    async def load(self) -> FearGreed | None:
        raw = await get_redis().get(KEY)
        if raw is None:
            return None
        data = json.loads(raw)
        return FearGreed(
            int(data["value"]), str(data["label"]), datetime.fromisoformat(data["measured_at"])
        )
