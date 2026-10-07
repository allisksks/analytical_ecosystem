from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import Field

from app.core.schemas import Schema

KbType = Literal["experiment", "research", "case", "incident_report", "playbook", "decision_log", "metric_definition"]


class LinkIn(Schema):
    kind: Literal["event", "metric", "dashboard", "experiment", "kb", "url"]
    ref: str = Field(max_length=500)
    title: str = Field(default="", max_length=300)


class ItemIn(Schema):
    project_id: uuid.UUID | None = None
    type: KbType
    title: str = Field(min_length=1, max_length=300)
    summary: str = Field(default="", max_length=2000)
    body: str = Field(default="", max_length=200_000)
    tags: list[str] = Field(default_factory=list, max_length=30)
    links: list[LinkIn] = Field(default_factory=list, max_length=50)
    decision: str = ""
    status: Literal["draft", "published"] = "published"


class ItemPatch(Schema):
    title: str | None = Field(default=None, max_length=300)
    summary: str | None = None
    body: str | None = None
    tags: list[str] | None = None
    links: list[LinkIn] | None = None
    decision: str | None = None
    status: Literal["draft", "published", "archived"] | None = None
    type: KbType | None = None


class ItemSummary(Schema):
    id: uuid.UUID
    project_id: uuid.UUID | None
    type: str
    title: str
    summary: str
    status: str
    decision: str
    tags: list[str]
    author_name: str
    version: int
    created_at: datetime
    updated_at: datetime


class KbCommentOut(Schema):
    id: uuid.UUID
    author_name: str
    text: str
    created_at: datetime


class AttachmentOut(Schema):
    id: uuid.UUID
    filename: str
    content_type: str
    size: int
    created_at: datetime


class ItemOut(ItemSummary):
    body: str
    links: list[dict[str, Any]]
    source_ref: str
    can_edit: bool = False
    comments: list[KbCommentOut] = Field(default_factory=list)
    attachments: list[AttachmentOut] = Field(default_factory=list)


class TagCount(Schema):
    tag: str
    count: int


class Facets(Schema):
    types: dict[str, int]
    tags: list[TagCount]


class SearchOut(Schema):
    items: list[ItemSummary]
    total: int
    facets: Facets


class KbVersionOut(Schema):
    version: int
    title: str
    summary: str
    body: str
    author: str
    created_at: datetime


class KbCommentIn(Schema):
    text: str = Field(min_length=1, max_length=5000)
