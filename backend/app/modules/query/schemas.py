from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import Field

from app.core.schemas import Schema


class RunIn(Schema):
    source_id: uuid.UUID
    project_id: uuid.UUID | None = None
    sql: str = Field(min_length=1, max_length=100_000)
    limit: int | None = Field(default=None, ge=1, le=100_000)
    use_cache: bool = True
    query_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{8,64}$")


class ResultColumnOut(Schema):
    name: str
    type: str


class RunOut(Schema):
    query_id: str
    columns: list[ResultColumnOut]
    rows: list[list[Any]]
    row_count: int
    truncated: bool
    elapsed_ms: float
    cached: bool
    executed_sql: str
    masked_columns: list[str]
    filtered_columns: list[str]


class ExportIn(RunIn):
    format: Literal["csv", "xlsx"] = "csv"


class HistoryOut(Schema):
    id: uuid.UUID
    source_id: uuid.UUID
    project_id: uuid.UUID | None
    origin: str
    sql: str
    status: str
    row_count: int | None
    elapsed_ms: float | None
    cached: bool
    error: str
    created_at: datetime


class SavedQueryIn(Schema):
    name: str = Field(min_length=1, max_length=200)
    description: str = ""
    sql: str = Field(min_length=1, max_length=100_000)
    source_id: uuid.UUID
    project_id: uuid.UUID | None = None
    shared: bool = True


class SavedQueryPatch(Schema):
    name: str | None = None
    description: str | None = None
    sql: str | None = None
    shared: bool | None = None


class SavedQueryOut(Schema):
    id: uuid.UUID
    name: str
    description: str
    sql: str
    source_id: uuid.UUID
    project_id: uuid.UUID | None
    owner_id: uuid.UUID | None
    shared: bool
    updated_at: datetime


class RlsRuleIn(Schema):
    column: str = Field(min_length=1, max_length=200)
    values: list[Any]
    project_id: uuid.UUID | None = None
    role_key: str | None = None
    description: str = ""
    enabled: bool = True


class RlsRuleOut(RlsRuleIn):
    id: uuid.UUID
