from dataclasses import dataclass


@dataclass
class Position:
    """`direction` defaults "long" - matches every existing position's real,
    implicit assumption exactly, so nothing changes until a "short" one
    actually exists (see docs/risk-engine.md#longshort-risk-semantics-planned)."""

    strategy_id: str
    asset: str
    notional_usd: float
    direction: str = "long"
    leverage: float = 1.0  # margin = notional / leverage

    @property
    def margin_usd(self) -> float:
        return self.notional_usd / self.leverage


@dataclass
class ProposedOrder:
    strategy_id: str
    asset: str
    notional_usd: float
    direction: str = "long"
    leverage: float = 1.0


@dataclass
class RiskDecision:
    approved: bool
    approved_notional_usd: float
    reason: str | None = None
