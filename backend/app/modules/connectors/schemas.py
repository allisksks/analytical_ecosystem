from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import Field

from app.core.schemas import Schema


class ConnectorType(Schema):
    type: str
    title: str
    dialect: str | None = None
    mode: str
    stage: str
    available: bool
    kind: str = ""
    config_schema: dict[str, Any] | None = None
    secret_fields: list[str] = Field(default_factory=list)


class SourceIn(Schema):
    name: str = Field(min_length=1, max_length=200)
    type: str
    config: dict[str, Any] = Field(default_factory=dict)
    project_ids: list[uuid.UUID] | None = None
    timeout_s: int = Field(default=60, ge=1, le=3600)
    row_limit: int = Field(default=10_000, ge=1, le=100_000)
    max_concurrency: int = Field(default=4, ge=1, le=64)
    cache_ttl_s: int = Field(default=900, ge=0, le=86_400)


class SourcePatch(Schema):
    name: str | None = None
    config: dict[str, Any] | None = None
    project_ids: list[uuid.UUID] | None = None
    all_projects: bool | None = None
    timeout_s: int | None = Field(default=None, ge=1, le=3600)
    row_limit: int | None = Field(default=None, ge=1, le=100_000)
    max_concurrency: int | None = Field(default=None, ge=1, le=64)
    cache_ttl_s: int | None = Field(default=None, ge=0, le=86_400)


class SourceTestIn(Schema):
    type: str
    config: dict[str, Any]
    source_id: uuid.UUID | None = None


class TestOut(Schema):
    ok: bool
    message: str
    latency_ms: float
    server_version: str


class SourceOut(Schema):
    id: uuid.UUID
    name: str
    type: str
    dialect: str
    mode: str
    config: dict[str, Any]
    project_ids: list[uuid.UUID] | None
    status: str
    last_error: str
    last_tested_at: datetime | None
    catalog_refreshed_at: datetime | None
    synced_at: datetime | None
    timeout_s: int
    row_limit: int
    max_concurrency: int
    cache_ttl_s: int
    is_demo: bool
    table_count: int = 0


class ColumnOut(Schema):
    id: uuid.UUID
    name: str
    data_type: str
    nullable: bool
    source_comment: str
    description: str
    is_pii: bool
    present: bool


class TableOut(Schema):
    id: uuid.UUID
    source_id: uuid.UUID
    schema_name: str
    name: str
    kind: str
    row_count: int | None
    last_modified: datetime | None
    source_comment: str
    description: str
    owner: str
    tags: list[str]
    present: bool
    columns: list[ColumnOut]


class TablePatch(Schema):
    description: str | None = None
    owner: str | None = None
    tags: list[str] | None = None


class ColumnPatch(Schema):
    description: str | None = None
    is_pii: bool | None = None


class RefreshOut(Schema):
    tables: int


class SyncOut(Schema):
    rows: dict[str, int]
