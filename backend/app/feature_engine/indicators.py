import math
from collections.abc import Sequence


def returns(closes: Sequence[float], periods_back: int) -> float | None:
    if len(closes) <= periods_back:
        return None
    latest = closes[-1]
    past = closes[-1 - periods_back]
    if past == 0:
        return None
    return (latest - past) / past


def momentum(closes: Sequence[float], window: int = 20) -> float | None:
    if len(closes) < window:
        return None
    sma = sum(closes[-window:]) / window
    if sma == 0:
        return None
    return (closes[-1] - sma) / sma


def volatility(closes: Sequence[float], window: int = 20) -> float | None:
    if len(closes) < window + 1:
        return None
    recent = closes[-window - 1 :]
    rets = [
        (recent[i] - recent[i - 1]) / recent[i - 1]
        for i in range(1, len(recent))
        if recent[i - 1] != 0
    ]
    if len(rets) < 2:
        return None
    mean = sum(rets) / len(rets)
    variance = sum((r - mean) ** 2 for r in rets) / (len(rets) - 1)
    return math.sqrt(variance)


def volatility_expansion_ratio(
    closes: Sequence[float], short_window: int = 10, long_window: int = 40
) -> float | None:
    """Recent realized volatility relative to its own longer-run baseline -
    not raw volatility(), whose absolute scale differs by asset. > 1 means a
    volatility squeeze is expanding right now (short-term vol above its own
    baseline), < 1 means it's still compressed - comparable across assets
    regardless of how volatile each one normally is."""
    short_vol = volatility(closes, short_window)
    long_vol = volatility(closes, long_window)
    if short_vol is None or long_vol is None or long_vol == 0:
        return None
    return short_vol / long_vol


def atr(
    highs: Sequence[float], lows: Sequence[float], closes: Sequence[float], window: int = 14
) -> float | None:
    if len(highs) < window + 1:
        return None
    true_ranges = []
    for i in range(len(highs) - window, len(highs)):
        prev_close = closes[i - 1]
        tr = max(highs[i] - lows[i], abs(highs[i] - prev_close), abs(lows[i] - prev_close))
        true_ranges.append(tr)
    return sum(true_ranges) / len(true_ranges)


def distance_from_high(closes: Sequence[float], window: int = 20) -> float | None:
    if len(closes) < window:
        return None
    rolling_high = max(closes[-window:])
    if rolling_high == 0:
        return None
    return (closes[-1] - rolling_high) / rolling_high


def distance_from_low(closes: Sequence[float], window: int = 20) -> float | None:
    if len(closes) < window:
        return None
    rolling_low = min(closes[-window:])
    if rolling_low == 0:
        return None
    return (closes[-1] - rolling_low) / rolling_low


def breakout_distance(closes: Sequence[float], window: int = 20) -> float | None:
    dh = distance_from_high(closes, window)
    dl = distance_from_low(closes, window)
    if dh is None or dl is None:
        return None
    return min(abs(dh), abs(dl))


def volume_z_score(volumes: Sequence[float], window: int = 20) -> float | None:
    if len(volumes) < window + 1:
        return None
    window_vols = volumes[-window - 1 : -1]
    mean = sum(window_vols) / len(window_vols)
    variance = sum((v - mean) ** 2 for v in window_vols) / (len(window_vols) - 1)
    stddev = math.sqrt(variance)
    if stddev == 0:
        return None
    return (volumes[-1] - mean) / stddev


def relative_volume(volumes: Sequence[float], window: int = 20) -> float | None:
    if len(volumes) < window + 1:
        return None
    window_vols = volumes[-window - 1 : -1]
    mean = sum(window_vols) / len(window_vols)
    if mean == 0:
        return None
    return volumes[-1] / mean


def volume_acceleration(volumes: Sequence[float], window: int = 10) -> float | None:
    if len(volumes) < window * 2:
        return None
    recent = volumes[-window:]
    older = volumes[-window * 2 : -window]
    recent_avg = sum(recent) / len(recent)
    older_avg = sum(older) / len(older)
    if older_avg == 0:
        return None
    return (recent_avg - older_avg) / older_avg


def funding_zscore(funding_rates: Sequence[float], window: int = 20) -> float | None:
    """How unusual the latest funding rate is relative to its own recent
    history, not an absolute magnitude - raw funding rates differ by asset
    (confirmed 2026-09-24: BTC/gold/SP500 are all ~1e-5 in magnitude, too
    small for any fixed cross-asset threshold to discriminate), but "3
    standard deviations below its own last 20 readings" is comparable
    across assets. Same z-score construction as volume_z_score above."""
    if len(funding_rates) < window + 1:
        return None
    window_rates = funding_rates[-window - 1 : -1]
    mean = sum(window_rates) / len(window_rates)
    variance = sum((r - mean) ** 2 for r in window_rates) / (len(window_rates) - 1)
    stddev = math.sqrt(variance)
    if stddev == 0:
        return None
    return (funding_rates[-1] - mean) / stddev


def oi_change(oi_values: Sequence[float], periods_back: int = 10) -> float | None:
    if len(oi_values) <= periods_back:
        return None
    latest = oi_values[-1]
    past = oi_values[-1 - periods_back]
    if past == 0:
        return None
    return (latest - past) / past
