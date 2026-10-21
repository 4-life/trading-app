from app.config import settings


def daily_loss_breached(daily_pnl_usd: float, capital_usd: float) -> bool:
    limit = -capital_usd * settings.daily_loss_limit_pct
    return daily_pnl_usd <= limit


def kill_switch_triggered(current_equity_usd: float, peak_equity_usd: float) -> bool:
    if peak_equity_usd <= 0:
        return False
    drawdown = (peak_equity_usd - current_equity_usd) / peak_equity_usd
    return drawdown >= settings.kill_switch_drawdown_pct
