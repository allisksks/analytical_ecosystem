from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import Field

from app.core.schemas import Schema


class AiStatus(Schema):
    enabled: bool
    cloud: bool
    allow_cloud: bool
    chat_model: str
    sql_model: str
    embedding_model: str | None
    indexed_items: int
    total_items: int
    reachable: bool | None = None
    error: str = ""


class AskIn(Schema):
    question: str = Field(min_length=2, max_length=2000)
    project_id: uuid.UUID | None = None


class Source(Schema):
    n: int
    item_id: uuid.UUID
    title: str
    type: str
    score: float = 0


class AskOut(Schema):
    interaction_id: uuid.UUID
    answer: str
    sources: list[Source]
    model: str
    latency_ms: float


class SqlIn(Schema):
    question: str = Field(min_length=2, max_length=2000)
    project_id: uuid.UUID
    source_id: uuid.UUID


class SqlOut(Schema):
    interaction_id: uuid.UUID
    sql: str
    explanation: str
    valid: bool
    error: str
    examples: list[str]
    model: str
    latency_ms: float


class DraftOut(Schema):
    interaction_id: uuid.UUID
    text: str
    model: str
    latency_ms: float


class WidgetDraftIn(Schema):
    project_id: uuid.UUID | None = None
    title: str = Field(max_length=300)
    columns: list[str] = Field(max_length=50)
    rows: list[list[Any]] = Field(max_length=500)


class FeedbackIn(Schema):
    rating: Literal[-1, 0, 1]
    comment: str = Field(default="", max_length=2000)


class InteractionOut(Schema):
    id: uuid.UUID
    kind: str
    user_id: uuid.UUID | None
    project_id: uuid.UUID | None
    question: str
    answer: str
    sql: str
    sources: list[dict[str, Any]]
    model: str
    latency_ms: float
    status: str
    error: str
    rating: int
    feedback: str
    created_at: datetime
