"""The VWAP + EMA9 lines and their BUY / SELL signals, without I/O - shared
by the VWAP executor, the backtests and the chart. See docs/vwap-strategy-engine.md#signals."""

from dataclasses import dataclass
from datetime import datetime

from app.order_queue import Direction

EMA_LENGTH = 9


@dataclass(frozen=True)
class Lines:
    """Per candle, oldest first. `vwap` is None before any volume in the session."""

    vwap: list[float | None]
    ema: list[float]


def session_vwap(
    times: list[datetime],
    highs: list[float],
    lows: list[float],
    closes: list[float],
    volumes: list[float],
) -> list[float | None]:
    """VWAP of the typical price (hlc3), reset at every UTC day - the
    TradingView "Session" anchor."""
    out: list[float | None] = []
    pv = vol = 0.0
    for k, t in enumerate(times):
        if k == 0 or t.date() != times[k - 1].date():
            pv = vol = 0.0
        typical = (highs[k] + lows[k] + closes[k]) / 3
        pv += typical * volumes[k]
        vol += volumes[k]
        out.append(pv / vol if vol > 0 else None)
    return out


def ema(values: list[float], n: int) -> list[float]:
    k = 2 / (n + 1)
    out = [values[0]]
    for v in values[1:]:
        out.append(out[-1] + k * (v - out[-1]))
    return out


def lines(
    times: list[datetime],
    highs: list[float],
    lows: list[float],
    closes: list[float],
    volumes: list[float],
) -> Lines:
    return Lines(session_vwap(times, highs, lows, closes, volumes), ema(closes, EMA_LENGTH))


def _side(close: float, vwap: float | None, ema_: float) -> int:
    """1 above both lines, -1 below both, 0 otherwise (or no VWAP)."""
    if vwap is None:
        return 0
    if close > ema_ and close > vwap:
        return 1
    if close < ema_ and close < vwap:
        return -1
    return 0


def signal_at(closes: list[float], ln: Lines, i: int) -> Direction | None:
    """Candle `i`'s signal: "long" (BUY) - its close above both lines, the
    previous one's not; "short" (SELL) the same below both."""
    if i < 1:
        return None
    now = _side(closes[i], ln.vwap[i], ln.ema[i])
    before = _side(closes[i - 1], ln.vwap[i - 1], ln.ema[i - 1])
    if now == 1 and before != 1:
        return "long"
    if now == -1 and before != -1:
        return "short"
    return None
