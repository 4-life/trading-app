from sqlalchemy import select

from app.db import async_session
from app.papers.models import ASSET_KINDS, AVERAGING_HEDGE, HEDGE_ASSET, Paper


async def paper_asset_timeframes(enabled_only: bool) -> list[tuple[str, str]]:
    """Distinct (asset, timeframe) pairs of papers - the scales market data
    and features are collected/backfilled on (an averaging hedge paper's
    hedge asset too). Backfill covers every paper;
    live computation only enabled ones."""
    query = (
        select(Paper.asset, Paper.timeframe, Paper.kind)
        .where(Paper.kind.in_(ASSET_KINDS))  # a scanner paper has no asset
        .distinct()
    )
    if enabled_only:
        query = query.where(Paper.enabled.is_(True))
    async with async_session() as session:
        rows = await session.execute(query)
    pairs: set[tuple[str, str]] = set()
    for asset, timeframe, kind in rows.all():
        pairs.add((asset, timeframe))
        if kind == AVERAGING_HEDGE:
            pairs.add((HEDGE_ASSET, timeframe))  # its short's candles
    return sorted(pairs)


async def executor_timeframes(executor: str) -> set[str]:
    """Timeframes of an executor's papers (enabled or disabled, scanners too)."""
    async with async_session() as session:
        rows = await session.scalars(
            select(Paper.timeframe).where(Paper.executor == executor).distinct()
        )
        return set(rows.all())
