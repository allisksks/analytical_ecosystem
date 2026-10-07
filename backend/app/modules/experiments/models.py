"""A/B experiments: design, lifecycle, result snapshots."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy import text as sql_text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, TimestampMixin, new_id

STATUSES = ("draft", "review", "running", "completed", "archived")
DECISIONS = ("", "ship", "keep_control", "inconclusive")


class Experiment(TimestampMixin, Base):
    __tablename__ = "experiments"
    __table_args__ = (UniqueConstraint("project_id", "key"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_id)
    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    key: Mapped[str] = mapped_column(String(120))  # value of experiment_key in the assignments table
    name: Mapped[str] = mapped_column(String(300))
    hypothesis: Mapped[str] = mapped_column(Text, default="")
    description: Mapped[str] = mapped_column(Text, default="")
    owner: Mapped[str] = mapped_column(String(200), default="")
    status: Mapped[str] = mapped_column(String(16), default="draft")
    # design
    metric_key: Mapped[str] = mapped_column(String(64))
    secondary_metrics: Mapped[list[str]] = mapped_column(ARRAY(String(64)), default=list)
    # [{"key": "A", "name": "Control", "weight": 0.5, "description": ""}], the first one is the control
    variants: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    traffic_share: Mapped[float] = mapped_column(Float, default=1.0)
    segments: Mapped[list[str]] = mapped_column(ARRAY(String(32)), default=list)
    mde: Mapped[float] = mapped_column(Float, default=0.05)  # relative minimal detectable effect
    alpha: Mapped[float] = mapped_column(Float, default=0.05)
    power: Mapped[float] = mapped_column(Float, default=0.8)
    baseline: Mapped[float | None] = mapped_column(Float)
    planned_users: Mapped[int | None] = mapped_column(Integer)
    planned_days: Mapped[int | None] = mapped_column(Integer)
    threshold: Mapped[float] = mapped_column(Float, default=0.95)  # stop when P(best) crosses it
    event_name: Mapped[str] = mapped_column(String(120), default="")  # related event of the registry
    # data
    splitter: Mapped[str] = mapped_column(String(16), default="external")  # external | internal
    salt: Mapped[str] = mapped_column(String(32), default="v1")
    source_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("data_sources.id", ondelete="SET NULL"))
    assignments_table: Mapped[str] = mapped_column(String(200), default="ab_assignments")
    # lifecycle and outcome
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    approved_by: Mapped[str] = mapped_column(String(320), default="")
    decision: Mapped[str] = mapped_column(String(16), default="")
    conclusion: Mapped[str] = mapped_column(Text, default="")
    decided_by: Mapped[str] = mapped_column(String(320), default="")
    kb_item_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("kb_items.id", ondelete="SET NULL"))
    created_by: Mapped[str] = mapped_column(String(320), default="")
    last_result: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    last_calculated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str] = mapped_column(Text, default="")


class ExperimentSnapshot(Base):
    """One recalculation: headline numbers for the history chart plus the full result."""

    __tablename__ = "experiment_snapshots"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_id)
    experiment_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("experiments.id", ondelete="CASCADE"), index=True)
    calculated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=sql_text("now()"))
    users: Mapped[int] = mapped_column(Integer, default=0)
    prob_best: Mapped[float | None] = mapped_column(Float)  # P(best treatment > control)
    lift: Mapped[float | None] = mapped_column(Float)
    result: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
