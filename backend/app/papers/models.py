from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

TIMEFRAMES = ("1m", "5m", "15m", "1h", "4h")
DIRECTIONS = ("long", "short", "both")
MODES = ("demo", "live")
DISABLED_BY = ("owner", "risk_engine", "scanner")
# Backtest only, for now (docs/papers.md#averaging-hedge-papers).
AVERAGING_HEDGE = "averaging_hedge"
HEDGE_ASSET = "ETH"  # an averaging hedge paper's short
KINDS = ("single", "scanner", "averaging", AVERAGING_HEDGE)
# The kinds that trade their own asset (a scanner only creates single papers).
TRADING_KINDS = ("single", "averaging")
# The kinds with an asset of their own: prepared (backfill, backtest) and charted.
ASSET_KINDS = (*TRADING_KINDS, AVERAGING_HEDGE)
# The kinds with position management (docs/papers.md#averaging-papers).
AVERAGING_KINDS = ("averaging", AVERAGING_HEDGE)
# A new paper is backfilled, then backtested, before it trades (docs/papers.md#preparation).
PREP_STATUSES = ("backfilling", "backtesting", "failed")
# A scanner paper's asset - it has none of its own (docs/papers.md#kinds).
MARKET = "*"


# An averaging paper's position management (docs/papers.md#averaging-papers).
POSITION_MANAGEMENT = (
    "initial_size_usd",
    "add_leverage",
    "add_size_usd",
    "max_drawdown_pct",
    "take_profit_pct",
    "backtest_start",
    "max_margin_usd",
    "intraday",
    "compound_margin",
    "reopen_in_trend",
)


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


class Paper(Base):
    """One strategy (`executor`) running on one asset - see docs/papers.md.
    A `scanner` paper has no asset (MARKET): it finds coins across the
    market and creates `single` papers for them (`parent_id`).

    Only one enabled live paper per asset: Hyperliquid nets one position per
    market per account, so a second live paper on the same asset would trade
    against the first. The slot frees up once the owner or the risk engine
    disables the live paper."""

    __tablename__ = "papers"
    __table_args__ = (
        CheckConstraint(_in("timeframe", TIMEFRAMES), name="ck_papers_timeframe"),
        CheckConstraint(_in("direction", DIRECTIONS), name="ck_papers_direction"),
        CheckConstraint(_in("mode", MODES), name="ck_papers_mode"),
        CheckConstraint(_in("kind", KINDS), name="ck_papers_kind"),
        CheckConstraint(
            f"prep_status IS NULL OR {_in('prep_status', PREP_STATUSES)}",
            name="ck_papers_prep_status",
        ),
        CheckConstraint(
            f"disabled_by IS NULL OR {_in('disabled_by', DISABLED_BY)}",
            name="ck_papers_disabled_by",
        ),
        CheckConstraint("leverage > 0", name="ck_papers_leverage"),
        Index(
            "uq_papers_live_asset",
            "asset",
            unique=True,
            postgresql_where=text("mode = 'live' AND enabled"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    asset: Mapped[str] = mapped_column(String, index=True)
    timeframe: Mapped[str] = mapped_column(String)
    leverage: Mapped[Decimal] = mapped_column(Numeric, default=Decimal("1.0"))
    direction: Mapped[str] = mapped_column(String)
    mode: Mapped[str] = mapped_column(String, default="demo")
    executor: Mapped[str] = mapped_column(String, index=True)
    kind: Mapped[str] = mapped_column(String, default="single", server_default="single")
    parent_id: Mapped[int | None] = mapped_column(
        ForeignKey("papers.id", ondelete="SET NULL"), nullable=True, index=True
    )
    # NULL = ready; otherwise the paper isn't traded yet.
    prep_status: Mapped[str | None] = mapped_column(String, nullable=True)
    prep_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    profitability_demo: Mapped[Decimal] = mapped_column(Numeric, default=Decimal(0))
    profitability_live: Mapped[Decimal] = mapped_column(Numeric, default=Decimal(0))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    # Creation or last re-enable - the risk engine's loss check counts only
    # positions closed since then.
    enabled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    disabled_by: Mapped[str | None] = mapped_column(String, nullable=True)
    disabled_reason: Mapped[str | None] = mapped_column(String, nullable=True)
    # An averaging paper's position management (docs/papers.md#averaging-papers),
    # NULL for the other kinds. Shares are fractions (0.3 = 30%).
    # The first entry's margin, fixed instead of the budget allocator's share.
    initial_size_usd: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    # Averaging down: a unit added whenever the margin left falls to
    # ADD_AT_MARGIN_LEFT, add_size_usd margin (default: initial_size_usd) at add_leverage.
    add_leverage: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    add_size_usd: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    # Optional give-up: close everything this far against the first buy (price);
    # the automatic one (OUT_OF_MARGIN_EXIT) applies anyway.
    max_drawdown_pct: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    # The take-profit floor: a strategy sell closes once the PnL is this share
    # of all the margin put in.
    take_profit_pct: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    # Where the averaging backtest starts trading; NULL = the whole stored history.
    backtest_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # The most margin a position may lock at once - adds beyond it are refused
    # (live by the risk engine, in the backtest skipped); NULL = no cap.
    max_margin_usd: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    # Close at the take-profit at once (no strategy sell needed) and keep
    # running after it - intraday trading instead of holding for a run.
    intraday: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    # Intraday only: after a take-profit, a fresh position at the close of the
    # candle it hit on while the strategy's trend lasts (REOPEN_IN_TREND).
    reopen_in_trend: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    # Profits compound: the max margin grows with the closed positions' realized
    # PnL (losses shrink it) - otherwise profits are banked, never re-risked.
    compound_margin: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    # A single paper's exits on top of its strategy's own, a share of the entry
    # price: the position closes at the first of these and its strategy's
    # exits (docs/papers.md#stop-loss-and-take-profit). NULL: none.
    stop_loss_pct: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    price_take_profit_pct: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
