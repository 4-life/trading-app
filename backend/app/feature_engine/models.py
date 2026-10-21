from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, Index, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class Feature(Base):
    """`interval` scopes a feature name to the candle scale it was computed
    from - the same feature name exists on every timeframe a paper uses."""

    __tablename__ = "features"
    __table_args__ = (
        Index(
            "ix_features_asset_name_interval_time",
            "asset",
            "name",
            "interval",
            "computed_at",
            unique=True,
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    asset: Mapped[str] = mapped_column(String, index=True)
    name: Mapped[str] = mapped_column(String, index=True)
    interval: Mapped[str] = mapped_column(String)
    value: Mapped[Decimal] = mapped_column(Numeric)
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
