"""Dashboards and their blocks (widgets)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base, TimestampMixin, new_id


class Dashboard(TimestampMixin, Base):
    __tablename__ = "dashboards"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_id)
    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    # NULL project = portfolio dashboard across all projects
    project_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    role: Mapped[str] = mapped_column(String(32), default="")  # audience of a template
    template_key: Mapped[str] = mapped_column(String(64), default="")
    owner_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    position: Mapped[int] = mapped_column(Integer, default=0)
    # default global filters: {"period_days": 30, "filters": [{"dimension": "platform", "values": ["ios"]}]}
    filters: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    cache_ttl_s: Mapped[int | None] = mapped_column(Integer)
    share_token: Mapped[str | None] = mapped_column(String(64), unique=True)
    share_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    widgets: Mapped[list[Widget]] = relationship(
        back_populates="dashboard", cascade="all, delete-orphan", order_by="Widget.position", lazy="selectin"
    )


class Widget(TimestampMixin, Base):
    __tablename__ = "widgets"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_id)
    dashboard_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("dashboards.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(200))
    viz: Mapped[str] = mapped_column(String(16))  # line | bar | area | heatmap | table | kpi | pie
    mode: Mapped[str] = mapped_column(String(16), default="semantic")  # semantic | sql
    # semantic: {metrics, dimensions, grain, filters}; sql: {source_id, sql}
    spec: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    layout: Mapped[dict[str, int]] = mapped_column(JSONB, default=dict)
    settings: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    position: Mapped[int] = mapped_column(Integer, default=0)
    observation: Mapped[str] = mapped_column(Text, default="")
    observation_author: Mapped[str] = mapped_column(String(320), default="")
    observation_is_ai_draft: Mapped[bool] = mapped_column(Boolean, default=False)

    dashboard: Mapped[Dashboard] = relationship(back_populates="widgets")


class DashboardGrant(Base):
    """Explicit access of an external guest to one dashboard, limited in time."""

    __tablename__ = "dashboard_grants"
    __table_args__ = (UniqueConstraint("dashboard_id", "user_id"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_id)
    dashboard_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("dashboards.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
