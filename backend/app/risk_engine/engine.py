from app.risk_engine.drawdown import daily_loss_breached, kill_switch_triggered
from app.risk_engine.limits import check_correlated_exposure, check_position_limit
from app.risk_engine.models import Position, ProposedOrder, RiskDecision


def evaluate(
    order: ProposedOrder,
    positions: list[Position],
    daily_pnl_usd: float,
    current_equity_usd: float,
    peak_equity_usd: float,
    capital_usd: float,
) -> RiskDecision:
    """Pure limit checks for one entry - see docs/risk-engine.md#limits.
    Everything is per mode: `capital_usd` is the mode's total."""
    if kill_switch_triggered(current_equity_usd, peak_equity_usd):
        return RiskDecision(
            approved=False,
            approved_notional_usd=0.0,
            reason="kill switch active: drawdown exceeded limit",
        )

    if daily_loss_breached(daily_pnl_usd, capital_usd):
        return RiskDecision(
            approved=False, approved_notional_usd=0.0, reason="daily loss limit breached"
        )

    notional = order.notional_usd

    position_cap = check_position_limit(order, capital_usd)
    if position_cap is not None:
        notional = min(notional, position_cap)

    exposure_cap = check_correlated_exposure(order, positions, capital_usd)
    if exposure_cap is not None:
        notional = min(notional, exposure_cap)

    if notional <= 0:
        return RiskDecision(
            approved=False,
            approved_notional_usd=0.0,
            reason="no room left under position/exposure limits",
        )

    reason = (
        None if notional == order.notional_usd else "resized down to fit position/exposure limits"
    )
    return RiskDecision(approved=True, approved_notional_usd=notional, reason=reason)
