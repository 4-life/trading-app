"""Backtest statistics shared by the risk engine (the same math as the
strategy chart's summary, docs/dashboard.md#strategy-chart)."""


def max_drawdown(returns_pct: list[float], leverage: float) -> float:
    """The deepest peak-to-trough drop (<= 0, a fraction) of equity
    compounded trade by trade, each trade on the whole margin: `returns_pct`
    are % of the entry notional, in closing order."""
    equity = peak = 1.0
    worst = 0.0
    for r in returns_pct:
        equity *= max(0.0, 1 + r * leverage / 100)
        peak = max(peak, equity)
        worst = min(worst, equity / peak - 1 if peak > 0 else -1.0)
    return worst
