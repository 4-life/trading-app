import logging

from app.config import settings
from app.feature_engine.engine import compute_and_store
from app.notifications.error_reporting import run_service
from app.papers.queries import paper_asset_timeframes
from app.scheduling import sleep_until_next

logger = logging.getLogger(__name__)


async def main() -> None:
    while True:
        # Re-read every pass, so a new paper's (asset, timeframe) is picked
        # up without a restart.
        for asset, timeframe in await paper_asset_timeframes(enabled_only=True):
            try:
                await compute_and_store(asset, timeframe)
            except Exception:
                logger.exception("feature computation failed for %s %s", asset, timeframe)
        # On the 5 s grid (:00, :05, ...) - one step before the executors (:01, :06, ...).
        await sleep_until_next(settings.feature_poll_seconds)


if __name__ == "__main__":
    run_service("feature-engine", main)
