from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class Setting(Base):
    """App settings from the dashboard's settings modal: integration keys
    (Hyperliquid, Telegram) and the auto-open switch. Secret values
    are stored encrypted (`encrypted = true`, `value` is the ciphertext)."""

    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String, primary_key=True)
    value: Mapped[str] = mapped_column(Text)
    encrypted: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class RiskEvent(Base):
    """Risk-engine actions: rejected orders, blocks, paper disables."""

    __tablename__ = "risk_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    paper_id: Mapped[int | None] = mapped_column(ForeignKey("papers.id"), nullable=True, index=True)
    type: Mapped[str] = mapped_column(String)
    detail: Mapped[str] = mapped_column(Text)


class SystemEvent(Base):
    """Watchdog and service events (failures, recoveries, restarts)."""

    __tablename__ = "system_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    source: Mapped[str] = mapped_column(String)
    level: Mapped[str] = mapped_column(String)  # "info" | "warning" | "critical"
    detail: Mapped[str] = mapped_column(Text)
