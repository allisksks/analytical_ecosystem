from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any, Literal

from pydantic import Field

from app.core.schemas import Schema


class DimensionOut(Schema):
    id: uuid.UUID
    key: str
    name: str
    column: str
    description: str


class DimensionIn(Schema):
    key: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    name: str
    column: str
    description: str = ""


class MetricBase(Schema):
    name: str = Field(min_length=1, max_length=200)
    description: str = ""
    table: str
    time_column: str
    expression: str = Field(min_length=1, max_length=4000)
    filters: str = ""
    maturity_days: int = Field(default=0, ge=0, le=365)
    default_dimensions: list[str] = Field(default_factory=list)
    format: Literal["number", "percent", "currency", "decimal"] = "number"
    owner: str = ""
    tags: list[str] = Field(default_factory=list)
    source_id: uuid.UUID | None = None


class MetricIn(MetricBase):
    key: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")


class MetricPatch(Schema):
    name: str | None = None
    description: str | None = None
    table: str | None = None
    time_column: str | None = None
    expression: str | None = None
    filters: str | None = None
    maturity_days: int | None = Field(default=None, ge=0, le=365)
    default_dimensions: list[str] | None = None
    format: Literal["number", "percent", "currency", "decimal"] | None = None
    owner: str | None = None
    tags: list[str] | None = None
    source_id: uuid.UUID | None = None


class MetricOut(MetricBase):
    id: uuid.UUID
    key: str
    pack: str
    version: int
    updated_at: datetime


class MetricVersionOut(Schema):
    version: int
    definition: dict[str, Any]
    author: str
    created_at: datetime


class FilterIn(Schema):
    dimension: str
    op: Literal["in", "not_in", "gte", "lte", "eq"] = "in"
    values: list[Any]


class CohortIn(Schema):
    label: str = Field(min_length=1, max_length=100)
    filters: list[FilterIn] = Field(default_factory=list)


class SemanticQueryIn(Schema):
    project_id: uuid.UUID | None = None
    metrics: list[str] = Field(min_length=1, max_length=20)
    dimensions: list[str] = Field(default_factory=list, max_length=5)
    grain: Literal["none", "day", "week", "month"] = "none"
    date_from: date | None = None
    date_to: date | None = None
    filters: list[FilterIn] = Field(default_factory=list)
    cohorts: list[CohortIn] = Field(default_factory=list, max_length=6)
    limit: int = Field(default=5000, ge=1, le=50_000)


class ColumnMeta(Schema):
    key: str
    name: str
    role: str
    format: str


class SemanticResultOut(Schema):
    columns: list[ColumnMeta]
    rows: list[list[Any]]
    sql: list[str]
    cached: bool


class InstallOut(Schema):
    metrics: int
    dimensions: int
