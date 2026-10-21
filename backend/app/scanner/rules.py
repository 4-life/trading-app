"""Scanner rules, pure (docs/papers.md#scanner-papers)."""

from dataclasses import dataclass, field
from typing import Any


def top_by_volume(meta: dict[str, Any], contexts: list[dict[str, Any]], n: int) -> list[str]:
    """The `n` listed perpetuals with the highest 24h notional volume."""
    ranked = sorted(
        (
            (float(ctx.get("dayNtlVlm") or 0), coin["name"])
            for coin, ctx in zip(meta["universe"], contexts, strict=False)
            if not coin.get("isDelisted")
        ),
        reverse=True,
    )
    return [name for _, name in ranked[:n]]


@dataclass(frozen=True)
class Child:
    """A single paper a scanner created."""

    paper_id: int
    asset: str
    enabled: bool
    disabled_by: str | None
    busy: bool  # an open position or an order in flight


@dataclass
class Plan:
    disable: list[int] = field(default_factory=list)
    enable: list[int] = field(default_factory=list)
    create: list[str] = field(default_factory=list)


def plan(
    children: list[Child],
    candidates: list[str],
    max_active: int,
    taken: set[str],
    scanning: bool = True,
) -> Plan:
    """`candidates`: coins breaking out now, best first. A flat child whose
    coin isn't one is disabled; a candidate gets an enabled child while there
    are free slots - re-enabling the coin's old child if the scanner disabled
    it, never one the owner or the risk engine disabled. `taken`: coins
    another paper already holds the slot for (live). `scanning` False (the
    scanner is disabled): disable every flat child, open nothing."""
    out = Plan()
    by_asset = {c.asset: c for c in children}
    for c in children:
        if c.enabled and not c.busy and (not scanning or c.asset not in candidates):
            out.disable.append(c.paper_id)
    if not scanning:
        return out
    active = sum(c.enabled and c.paper_id not in out.disable for c in children)
    for asset in candidates:
        if active >= max_active:
            break
        child = by_asset.get(asset)
        if asset in taken or (child is not None and child.enabled):
            continue
        if child is None:
            out.create.append(asset)
        elif child.disabled_by == "scanner":
            out.enable.append(child.paper_id)
        else:
            continue
        active += 1
    return out
