from sqlalchemy import select

from app.db import async_session
from app.papers.models import TRADING_KINDS, Paper


async def paper_asset_timeframes(enabled_only: bool) -> list[tuple[str, str]]:
    """Distinct (asset, timeframe) pairs of papers - the scales market data
    and features are collected/backfilled on. Backfill covers every paper;
    live computation only enabled ones."""
    query = (
        select(Paper.asset, Paper.timeframe)
        .where(Paper.kind.in_(TRADING_KINDS))  # a scanner paper has no asset
        .distinct()
    )
    if enabled_only:
        query = query.where(Paper.enabled.is_(True))
    async with async_session() as session:
        rows = await session.execute(query)
    return sorted(rows.tuples().all())


async def executor_timeframes(executor: str) -> set[str]:
    """Timeframes of an executor's papers (enabled or disabled, scanners too)."""
    async with async_session() as session:
        rows = await session.scalars(
            select(Paper.timeframe).where(Paper.executor == executor).distinct()
        )
        return set(rows.all())
