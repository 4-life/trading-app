"""The market-data adapter for the selected exchange API's provider
(app/system/exchange_api.py) - Hyperliquid without one."""

import asyncio
import logging
import os

from app.exchange.base import MarketAdapter
from app.exchange.hyperliquid import HyperliquidAdapter
from app.exchange.lighter import LighterAdapter
from app.system.exchange_api import DataSource, data_source

logger = logging.getLogger(__name__)

SOURCE_CHECK_SECONDS = 15


def market_adapter(source: DataSource) -> MarketAdapter:
    if source.provider == "lighter":
        return LighterAdapter(source.url)
    return HyperliquidAdapter(source.url)


async def connected_adapter(*, skip_ws: bool = True) -> tuple[DataSource, MarketAdapter]:
    source = await data_source()
    adapter = market_adapter(source)
    await adapter.connect(skip_ws=skip_ws)
    logger.info("market data: %s", source.provider)
    return source, adapter


async def exit_on_source_change(source: DataSource) -> None:
    """For long-running services: exits when the exchange API's provider
    changes, so Docker restarts the service on the new one."""
    while True:
        await asyncio.sleep(SOURCE_CHECK_SECONDS)
        try:
            current = await data_source()
        except Exception:
            logger.exception("could not read the exchange API - keeping %s", source)
            continue
        if current != source:
            logger.warning("exchange API changed (%s -> %s) - restarting", source, current)
            os._exit(0)
