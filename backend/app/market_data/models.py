from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, Index, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class Trade(Base):
    __tablename__ = "trades"
    __table_args__ = (Index("ix_trades_asset_time", "asset", "exchange_timestamp"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    asset: Mapped[str] = mapped_column(String, index=True)
    price: Mapped[Decimal] = mapped_column(Numeric)
    size: Mapped[Decimal] = mapped_column(Numeric)
    side: Mapped[str] = mapped_column(String)
    exchange_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class OrderBookSnapshot(Base):
    __tablename__ = "order_book_snapshots"
    __table_args__ = (Index("ix_obs_asset_time", "asset", "exchange_timestamp"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    asset: Mapped[str] = mapped_column(String, index=True)
    best_bid: Mapped[Decimal] = mapped_column(Numeric)
    best_ask: Mapped[Decimal] = mapped_column(Numeric)
    bid_depth: Mapped[Decimal] = mapped_column(Numeric)
    ask_depth: Mapped[Decimal] = mapped_column(Numeric)
    exchange_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Candle(Base):
    __tablename__ = "candles"
    __table_args__ = (
        Index(
            "ix_candles_asset_interval_time",
            "asset",
            "interval",
            "open_time",
            unique=True,
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    asset: Mapped[str] = mapped_column(String, index=True)
    interval: Mapped[str] = mapped_column(String)
    open: Mapped[Decimal] = mapped_column(Numeric)
    high: Mapped[Decimal] = mapped_column(Numeric)
    low: Mapped[Decimal] = mapped_column(Numeric)
    close: Mapped[Decimal] = mapped_column(Numeric)
    volume: Mapped[Decimal] = mapped_column(Numeric)
    open_time: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class FundingRate(Base):
    __tablename__ = "funding_rates"
    __table_args__ = (Index("ix_funding_asset_time", "asset", "exchange_timestamp", unique=True),)

    id: Mapped[int] = mapped_column(primary_key=True)
    asset: Mapped[str] = mapped_column(String, index=True)
    funding_rate: Mapped[Decimal] = mapped_column(Numeric)
    premium: Mapped[Decimal] = mapped_column(Numeric)
    exchange_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class OpenInterestSnapshot(Base):
    __tablename__ = "open_interest_snapshots"
    __table_args__ = (Index("ix_oi_asset_time", "asset", "collected_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    asset: Mapped[str] = mapped_column(String, index=True)
    open_interest: Mapped[Decimal] = mapped_column(Numeric)
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class MarketLimit(Base):
    """A provider's margin limits for one perpetual, stored by market data on
    start (app/market_data/limits.py): the most leverage a position may take
    and the maintenance margin - the share of the notional under which the
    exchange liquidates it."""

    __tablename__ = "market_limits"

    provider: Mapped[str] = mapped_column(String, primary_key=True)
    asset: Mapped[str] = mapped_column(String, primary_key=True)
    max_leverage: Mapped[Decimal] = mapped_column(Numeric)
    maintenance_margin: Mapped[Decimal] = mapped_column(Numeric)  # of the notional
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
