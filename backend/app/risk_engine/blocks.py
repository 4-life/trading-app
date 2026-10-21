"""Risk-engine blocks on opening new positions (see docs/risk-engine.md).
Set by the risk-engine service, checked by every executor before an entry.
Exits are never blocked."""

from app.watchdog.redis_client import get_redis

_EXECUTOR_KEY = "risk:block:executor:{}"
_PAPER_KEY = "risk:block:paper:{}"


async def is_entry_blocked(executor: str, paper_id: int) -> bool:
    return bool(
        await get_redis().exists(_EXECUTOR_KEY.format(executor), _PAPER_KEY.format(paper_id))
    )


async def block_reason(executor: str, paper_id: int) -> str | None:
    """Why new entries are blocked for this paper (its own block first, then
    its executor's), or None."""
    redis = get_redis()
    for key in (_PAPER_KEY.format(paper_id), _EXECUTOR_KEY.format(executor)):
        reason = await redis.get(key)
        if reason is not None:
            return str(reason)
    return None


async def block_executor(executor: str, reason: str) -> None:
    await get_redis().set(_EXECUTOR_KEY.format(executor), reason)


async def unblock_executor(executor: str) -> None:
    await get_redis().delete(_EXECUTOR_KEY.format(executor))


async def block_paper(paper_id: int, reason: str) -> None:
    await get_redis().set(_PAPER_KEY.format(paper_id), reason)


async def unblock_paper(paper_id: int) -> None:
    await get_redis().delete(_PAPER_KEY.format(paper_id))
