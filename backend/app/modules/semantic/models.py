"""Semantic layer: metrics and dimensions defined once and reused by dashboards, experiments and AI."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import ARRAY, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, TimestampMixin, new_id


class Dimension(TimestampMixin, Base):
    __tablename__ = "dimensions"
    __table_args__ = (UniqueConstraint("org_id", "key"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_id)
    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    key: Mapped[str] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(200))
    column: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")


class Metric(TimestampMixin, Base):
    __tablename__ = "metrics"
    __table_args__ = (UniqueConstraint("org_id", "key"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_id)
    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    key: Mapped[str] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    # where: optional fixed source; otherwise the first source of the project whose catalog has the table
    source_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("data_sources.id", ondelete="SET NULL"))
    table: Mapped[str] = mapped_column(String(200))
    time_column: Mapped[str] = mapped_column(String(200))
    expression: Mapped[str] = mapped_column(Text)
    filters: Mapped[str] = mapped_column(Text, default="")
    maturity_days: Mapped[int] = mapped_column(Integer, default=0)
    default_dimensions: Mapped[list[str]] = mapped_column(ARRAY(String(64)), default=list)
    format: Mapped[str] = mapped_column(String(16), default="number")
    owner: Mapped[str] = mapped_column(String(200), default="")
    tags: Mapped[list[str]] = mapped_column(ARRAY(String(64)), default=list)
    pack: Mapped[str] = mapped_column(String(32), default="")
    version: Mapped[int] = mapped_column(Integer, default=1)


class MetricVersion(Base):
    """Append-only history of metric definitions (who changed the formula and when)."""

    __tablename__ = "metric_versions"
    __table_args__ = (UniqueConstraint("metric_id", "version"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_id)
    metric_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("metrics.id", ondelete="CASCADE"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    definition: Mapped[dict[str, Any]] = mapped_column(JSONB)
    author: Mapped[str] = mapped_column(String(320), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"))
