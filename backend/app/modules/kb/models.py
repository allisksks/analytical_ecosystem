"""Knowledge base: institutional memory (experiments, research, incidents, playbooks, decisions…)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, Computed, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy import text as sql_text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, TSVECTOR, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, TimestampMixin, new_id

KB_TYPES = ("experiment", "research", "case", "incident_report", "playbook", "decision_log", "metric_definition")

SEARCH_EXPR = (
    "setweight(to_tsvector('russian', coalesce(title, '')), 'A') || "
    "setweight(to_tsvector('russian', coalesce(summary, '')), 'B') || "
    "setweight(to_tsvector('russian', kb_tags_text(tags)), 'B') || "
    "setweight(to_tsvector('russian', coalesce(body, '')), 'C')"
)


class KnowledgeItem(TimestampMixin, Base):
    __tablename__ = "kb_items"
    __table_args__ = (
        Index("ix_kb_items_search", "search", postgresql_using="gin"),
        Index("ix_kb_items_tags", "tags", postgresql_using="gin"),
        Index("ix_kb_items_title_trgm", "title", postgresql_using="gin", postgresql_ops={"title": "gin_trgm_ops"}),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_id)
    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    # NULL = organisation-wide knowledge (methodology, playbooks)
    project_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    type: Mapped[str] = mapped_column(String(32))
    title: Mapped[str] = mapped_column(String(300))
    summary: Mapped[str] = mapped_column(Text, default="")
    body: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(16), default="published")  # draft | published | archived
    decision: Mapped[str] = mapped_column(String(32), default="")  # accepted | rejected | inconclusive | …
    tags: Mapped[list[str]] = mapped_column(ARRAY(String(64)), default=list)
    # [{"kind": "event|metric|dashboard|experiment|kb|url", "ref": "...", "title": "..."}]
    links: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    author_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    author_name: Mapped[str] = mapped_column(String(200), default="")
    source_ref: Mapped[str] = mapped_column(String(200), default="")  # e.g. experiment id that produced the item
    version: Mapped[int] = mapped_column(Integer, default=1)
    search = mapped_column(TSVECTOR, Computed(SEARCH_EXPR, persisted=True))


class KnowledgeVersion(Base):
    __tablename__ = "kb_versions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_id)
    item_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("kb_items.id", ondelete="CASCADE"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String(300))
    summary: Mapped[str] = mapped_column(Text, default="")
    body: Mapped[str] = mapped_column(Text, default="")
    author: Mapped[str] = mapped_column(String(320), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=sql_text("now()"))


class KnowledgeComment(Base):
    __tablename__ = "kb_comments"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_id)
    item_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("kb_items.id", ondelete="CASCADE"), index=True)
    author_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    author_name: Mapped[str] = mapped_column(String(200))
    text: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=sql_text("now()"))


class KnowledgeAttachment(Base):
    __tablename__ = "kb_attachments"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_id)
    item_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("kb_items.id", ondelete="CASCADE"), index=True)
    filename: Mapped[str] = mapped_column(String(255))
    content_type: Mapped[str] = mapped_column(String(100))
    size: Mapped[int] = mapped_column(BigInteger)
    path: Mapped[str] = mapped_column(String(500))
    uploaded_by: Mapped[str] = mapped_column(String(320), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=sql_text("now()"))
