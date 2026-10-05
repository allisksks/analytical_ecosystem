from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any, Literal

from pydantic import Field

from app.core.schemas import Schema
from app.modules.semantic.schemas import ColumnMeta, FilterIn

Viz = Literal["line", "bar", "area", "heatmap", "table", "kpi", "pie"]


class WidgetIn(Schema):
    title: str = Field(min_length=1, max_length=200)
    viz: Viz
    mode: Literal["semantic", "sql"] = "semantic"
    spec: dict[str, Any]
    layout: dict[str, int] = Field(default_factory=lambda: {"x": 0, "y": 0, "w": 6, "h": 4})
    settings: dict[str, Any] = Field(default_factory=dict)
    observation: str = ""


class WidgetPatch(Schema):
    title: str | None = None
    viz: Viz | None = None
    mode: Literal["semantic", "sql"] | None = None
    spec: dict[str, Any] | None = None
    layout: dict[str, int] | None = None
    settings: dict[str, Any] | None = None
    observation: str | None = None


class WidgetOut(Schema):
    id: uuid.UUID
    title: str
    viz: str
    mode: str
    spec: dict[str, Any]
    layout: dict[str, int]
    settings: dict[str, Any]
    position: int
    observation: str
    observation_author: str
    observation_is_ai_draft: bool


class DashboardIn(Schema):
    project_id: uuid.UUID | None = None
    title: str = Field(min_length=1, max_length=200)
    description: str = ""
    filters: dict[str, Any] = Field(default_factory=lambda: {"period_days": 30})


class FromTemplateIn(Schema):
    project_id: uuid.UUID | None = None
    template_key: str


class DashboardPatch(Schema):
    title: str | None = None
    description: str | None = None
    filters: dict[str, Any] | None = None
    position: int | None = None


class DashboardSummary(Schema):
    id: uuid.UUID
    project_id: uuid.UUID | None
    title: str
    description: str
    role: str
    template_key: str
    owner_id: uuid.UUID | None
    position: int
    updated_at: datetime
    can_edit: bool = False


class DashboardOut(DashboardSummary):
    filters: dict[str, Any]
    widgets: list[WidgetOut]
    share_expires_at: datetime | None
    shared: bool = False


class TemplateOut(Schema):
    key: str
    title: str
    role: str
    scope: str
    widgets: int


class LayoutItem(Schema):
    id: uuid.UUID
    layout: dict[str, int]


class DataIn(Schema):
    date_from: date | None = None
    date_to: date | None = None
    filters: list[FilterIn] = Field(default_factory=list)


class PreviewIn(DataIn):
    project_id: uuid.UUID | None = None
    mode: Literal["semantic", "sql"] = "semantic"
    spec: dict[str, Any]


class DataOut(Schema):
    columns: list[ColumnMeta]
    rows: list[list[Any]]
    sql: list[str]
    cached: bool
    date_from: date
    date_to: date


class ShareIn(Schema):
    ttl_days: int = Field(default=7, ge=1, le=90)


class ShareOut(Schema):
    token: str
    expires_at: datetime


class GrantIn(Schema):
    user_id: uuid.UUID
    expires_at: datetime | None = None
