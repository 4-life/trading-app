from app.config import settings
from app.risk_engine.models import Position, ProposedOrder


def _correlated_group(asset: str) -> list[str] | None:
    for group in settings.correlated_asset_groups:
        if asset in group:
            return group
    return None


def check_position_limit(order: ProposedOrder, capital_usd: float) -> float | None:
    """Max notional allowed for a single position, or None if the order
    already fits under the limit. The limit is on the position's MARGIN
    (notional / leverage), so leverage scales the position - docs/risk-engine.md#limits.
    `capital_usd` is the mode's total."""
    max_notional = capital_usd * settings.max_position_pct * order.leverage
    if order.notional_usd > max_notional:
        return max_notional
    return None


def _signed(direction: str, value: float) -> float:
    return value if direction == "long" else -value


def check_correlated_exposure(
    order: ProposedOrder, positions: list[Position], capital_usd: float
) -> float | None:
    """Max additional notional allowed for `order.asset` given existing
    margin across its correlated group (the limit is on margin, like the
    position limit) (see docs/risk-engine.md#event--halt-gates
    for the equity cluster this was originally written for; BTC+ETH are
    treated the same way here), or None if it already fits.

    Nets LONG and SHORT within the group instead of summing raw notional
    (see docs/risk-engine.md#longshort-risk-semantics-planned) - a BTC long
    and a BTC short aren't the same directional bet twice, they partially
    offset. Solved directly for the largest margin x such that
    |existing_net + sign*x| <= max_group_margin, where sign is +1 for
    a long order and -1 for a short one - this also correctly handles an
    order large enough to flip the net exposure from one side of zero to
    the other (e.g. a large short against a smaller existing long), not
    just simple same-direction stacking."""
    group = _correlated_group(order.asset)
    if group is None:
        return None
    existing_net = sum(_signed(p.direction, p.margin_usd) for p in positions if p.asset in group)
    max_group_margin = capital_usd * settings.max_correlated_exposure_pct
    sign = 1.0 if order.direction == "long" else -1.0
    max_addable_margin = max_group_margin - sign * existing_net
    approved = min(order.notional_usd, max(max_addable_margin, 0.0) * order.leverage)
    if approved < order.notional_usd:
        return approved
    return None
