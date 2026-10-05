"""AI assistant: interaction log (answers, generated SQL, drafts + feedback) and knowledge-base chunks."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import DateTime, Float, ForeignKey, Integer, SmallInteger, String, Text
from sqlalchemy import text as sql_text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, new_id

KINDS = ("ask", "sql", "draft_experiment", "draft_widget")


class AiInteraction(Base):
    """Every model call made on behalf of a user — for quality review, the golden set and the audit."""

    __tablename__ = "ai_interactions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_id)
    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    project_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("projects.id", ondelete="SET NULL"))
    kind: Mapped[str] = mapped_column(String(32))
    question: Mapped[str] = mapped_column(Text, default="")
    answer: Mapped[str] = mapped_column(Text, default="")
    sql: Mapped[str] = mapped_column(Text, default="")
    # [{"n": 1, "item_id": "...", "title": "...", "score": 0.8}]
    sources: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    model: Mapped[str] = mapped_column(String(200), default="")
    latency_ms: Mapped[float] = mapped_column(Float, default=0)
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(16), default="ok")  # ok | error | rejected
    error: Mapped[str] = mapped_column(Text, default="")
    rating: Mapped[int] = mapped_column(SmallInteger, default=0)  # -1 | 0 | 1
    feedback: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=sql_text("now()"))


class KbChunk(Base):
    """A passage of a knowledge-base record; ``embedding`` is NULL until an embedding model is configured."""

    __tablename__ = "ai_kb_chunks"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_id)
    item_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("kb_items.id", ondelete="CASCADE"), index=True)
    item_version: Mapped[int] = mapped_column(Integer)
    chunk_no: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    embedding_model: Mapped[str] = mapped_column(String(200), default="")
    # dimension depends on the model (768 nomic-embed-text, 256 Yandex text-search), so it is not fixed
    embedding: Mapped[list[float] | None] = mapped_column(Vector())
