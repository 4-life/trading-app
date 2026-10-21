from collections.abc import Sequence


def bid_ask_imbalance(bid_depth: float, ask_depth: float) -> float | None:
    total = bid_depth + ask_depth
    if total == 0:
        return None
    return (bid_depth - ask_depth) / total


def market_depth(bid_depth: float, ask_depth: float) -> float:
    return bid_depth + ask_depth


def spread(best_bid: float, best_ask: float) -> float | None:
    mid = (best_bid + best_ask) / 2
    if mid == 0:
        return None
    return (best_ask - best_bid) / mid


def aggressive_buy_sell_ratio(trades: Sequence[tuple[str, float]]) -> float | None:
    if not trades:
        return None
    buy_volume = sum(size for side, size in trades if side == "B")
    total_volume = sum(size for _, size in trades)
    if total_volume == 0:
        return None
    return buy_volume / total_volume
