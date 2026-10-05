"""Event registry (EMS): events, append-only versions, global parameters, validation runs, alerts, channels."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, LargeBinary, String, Text, UniqueConstraint
from sqlalchemy import text as sql_text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, TimestampMixin, new_id

EVENT_STATUSES = ("draft", "active", "deprecated", "archived")
PARAM_TYPES = ("string", "int", "float", "bool", "enum", "timestamp", "json")


class Event(TimestampMixin, Base):
    __tablename__ = "ems_events"
    __table_args__ = (UniqueConstraint("project_id", "name"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_id)
    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(Text, default="")
    category: Mapped[str] = mapped_column(String(64), default="")
    owner: Mapped[str] = mapped_column(String(200), default="")
    status: Mapped[str] = mapped_column(String(16), default="draft")
    # GQM: the business goal and question the event answers, and the metrics computed from it
    goal: Mapped[str] = mapped_column(Text, default="")
    question: Mapped[str] = mapped_column(Text, default="")
    metric_keys: Mapped[list[str]] = mapped_column(ARRAY(String(64)), default=list)
    tags: Mapped[list[str]] = mapped_column(ARRAY(String(64)), default=list)
    current_version: Mapped[str | None] = mapped_column(String(32))  # latest approved semver
    created_by: Mapped[str] = mapped_column(String(320), default="")


class EventVersion(Base):
    """Append-only: a version is never edited after approval; changes create a new version."""

    __tablename__ = "ems_event_versions"
    __table_args__ = (UniqueConstraint("event_id", "version"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_id)
    event_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("ems_events.id", ondelete="CASCADE"), index=True)
    version: Mapped[str] = mapped_column(String(32))
    major: Mapped[int] = mapped_column(Integer)
    minor: Mapped[int] = mapped_column(Integer)
    patch: Mapped[int] = mapped_column(Integer)
    # [{"name", "type", "required", "description", "enum": [...], "global": bool}]
    params: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    description: Mapped[str] = mapped_column(Text, default="")
    changelog: Mapped[str] = mapped_column(Text, default="")
    app_version: Mapped[str] = mapped_column(String(32), default="")  # first release carrying this version
    status: Mapped[str] = mapped_column(String(16), default="pending")  # pending | approved | rejected
    author: Mapped[str] = mapped_column(String(320), default="")
    reviewed_by: Mapped[str] = mapped_column(String(320), default="")
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    review_comment: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=sql_text("now()"))


class GlobalParam(TimestampMixin, Base):
    """Parameters inherited by every event of the organisation (user_id, platform, app_version…)."""

    __tablename__ = "ems_global_params"
    __table_args__ = (UniqueConstraint("org_id", "name"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_id)
    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    type: Mapped[str] = mapped_column(String(16))
    required: Mapped[bool] = mapped_column(Boolean, default=True)
    description: Mapped[str] = mapped_column(Text, default="")
    enum: Mapped[list[str]] = mapped_column(ARRAY(String(120)), default=list)


class EventComment(Base):
    __tablename__ = "ems_event_comments"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_id)
    event_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("ems_events.id", ondelete="CASCADE"), index=True)
    author: Mapped[str] = mapped_column(String(320))
    text: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=sql_text("now()"))


class TrackingConfig(TimestampMixin, Base):
    """Where the raw events of a project live (used by validation and auto-description)."""

    __tablename__ = "ems_tracking_configs"

    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True)
    source_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("data_sources.id", ondelete="CASCADE"))
    table: Mapped[str] = mapped_column(String(200), default="events")
    name_column: Mapped[str] = mapped_column(String(200), default="event_name")
    time_column: Mapped[str] = mapped_column(String(200), default="event_ts")
    date_column: Mapped[str] = mapped_column(String(200), default="event_date")
    params_column: Mapped[str] = mapped_column(String(200), default="params")
    user_column: Mapped[str] = mapped_column(String(200), default="user_id")
    platform_column: Mapped[str] = mapped_column(String(200), default="platform")
    version_column: Mapped[str] = mapped_column(String(200), default="app_version")
    drop_threshold: Mapped[float] = mapped_column(default=0.5)  # alert when volume < 50% of baseline


class ValidationRun(Base):
    __tablename__ = "ems_validation_runs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_id)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=sql_text("now()"))
    data_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(16), default="ok")  # ok | warning | critical | error
    summary: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    # per event: {"event": name, "status", "count", "baseline", "checks": [...]}
    results: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    error: Mapped[str] = mapped_column(Text, default="")


class Alert(Base):
    __tablename__ = "ems_alerts"
    __table_args__ = (Index("ix_ems_alerts_project_status", "project_id", "status"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_id)
    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    event_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("ems_events.id", ondelete="CASCADE"))
    event_name: Mapped[str] = mapped_column(String(120), default="")
    kind: Mapped[str] = mapped_column(
        String(32)
    )  # missing | volume_drop | release_regression | type_mismatch | required_empty | stale_data
    severity: Mapped[str] = mapped_column(String(16))  # warning | critical
    title: Mapped[str] = mapped_column(String(300))
    message: Mapped[str] = mapped_column(Text, default="")
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    fingerprint: Mapped[str] = mapped_column(String(200), index=True)  # dedup of the same open problem
    status: Mapped[str] = mapped_column(String(16), default="open")  # open | acknowledged | resolved
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=sql_text("now()"))
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=sql_text("now()"))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    acknowledged_by: Mapped[str] = mapped_column(String(320), default="")


class NotificationChannel(TimestampMixin, Base):
    __tablename__ = "notification_channels"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_id)
    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    kind: Mapped[str] = mapped_column(String(16))  # slack | mattermost | telegram | email
    config: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)  # non-secret part
    secrets_encrypted: Mapped[bytes | None] = mapped_column(LargeBinary)
    min_severity: Mapped[str] = mapped_column(String(16), default="warning")
    project_ids: Mapped[list[uuid.UUID] | None] = mapped_column(ARRAY(UUID(as_uuid=True)))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
