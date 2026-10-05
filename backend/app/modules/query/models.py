"""Query history, saved queries and extra row-level security rules."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, TimestampMixin, new_id


class QueryRun(Base):
    __tablename__ = "query_runs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_id)
    org_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), index=True)
    source_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("data_sources.id", ondelete="CASCADE"))
    project_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    origin: Mapped[str] = mapped_column(String(32), default="sql_editor")  # sql_editor | widget | semantic | ai
    sql: Mapped[str] = mapped_column(Text)
    executed_sql: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(16))  # ok | error | cancelled | timeout | denied
    row_count: Mapped[int | None] = mapped_column(Integer)
    elapsed_ms: Mapped[float | None] = mapped_column(Float)
    cached: Mapped[bool] = mapped_column(Boolean, default=False)
    error: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"), index=True)


class SavedQuery(TimestampMixin, Base):
    __tablename__ = "saved_queries"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_id)
    org_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    project_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    source_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("data_sources.id", ondelete="CASCADE"))
    owner_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    sql: Mapped[str] = mapped_column(Text)
    shared: Mapped[bool] = mapped_column(Boolean, default=True)


class RlsRule(TimestampMixin, Base):
    """Additional row filter on top of the project data scope, e.g. "role marketing sees source <> 'organic'".

    Applied to every table that has ``column`` in queries of users holding ``role_key`` (any role when NULL)
    inside ``project_id`` (every project when NULL)."""

    __tablename__ = "rls_rules"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_id)
    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    project_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    role_key: Mapped[str | None] = mapped_column(String(64))
    column: Mapped[str] = mapped_column(String(200))
    values: Mapped[list[Any]] = mapped_column(JSONB, default=list)
    description: Mapped[str] = mapped_column(Text, default="")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
