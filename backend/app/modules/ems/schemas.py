from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import Field

from app.core.schemas import Schema


class ParamIn(Schema):
    name: str
    type: Literal["string", "int", "float", "bool", "enum", "timestamp", "json"] = "string"
    required: bool = False
    description: str = ""
    enum: list[str] = Field(default_factory=list)


class EventIn(Schema):
    project_id: uuid.UUID
    name: str = Field(min_length=1, max_length=120)
    description: str = ""
    category: str = ""
    owner: str = ""
    goal: str = ""
    question: str = ""
    metric_keys: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    params: list[ParamIn] = Field(default_factory=list)
    app_version: str = ""


class EventPatch(Schema):
    category: str | None = None
    owner: str | None = None
    goal: str | None = None
    question: str | None = None
    metric_keys: list[str] | None = None
    tags: list[str] | None = None


class VersionIn(Schema):
    params: list[ParamIn]
    description: str | None = None
    changelog: str = ""
    app_version: str = ""


class ReviewIn(Schema):
    approve: bool
    comment: str = ""


class StatusIn(Schema):
    status: Literal["active", "deprecated", "archived"]
    reason: str = ""


class EventVersionOut(Schema):
    id: uuid.UUID
    version: str
    params: list[dict[str, Any]]
    description: str
    changelog: str
    app_version: str
    status: str
    author: str
    reviewed_by: str
    reviewed_at: datetime | None
    review_comment: str
    created_at: datetime


class EventSummary(Schema):
    id: uuid.UUID
    project_id: uuid.UUID
    name: str
    description: str
    category: str
    owner: str
    status: str
    current_version: str | None
    metric_keys: list[str]
    tags: list[str]
    updated_at: datetime
    pending_version: str | None = None
    open_alerts: int = 0
    health: str = "unknown"  # ok | warning | critical | unknown (from the last validation)
    last_count: int | None = None


class EventCommentOut(Schema):
    id: uuid.UUID
    author: str
    text: str
    created_at: datetime


class EventOut(EventSummary):
    goal: str
    question: str
    created_by: str
    versions: list[EventVersionOut]
    comments: list[EventCommentOut]


class DiffOut(Schema):
    from_version: str
    to_version: str
    bump: str
    changes: list[dict[str, Any]]


class EventCommentIn(Schema):
    text: str = Field(min_length=1, max_length=5000)


class GlobalParamIn(ParamIn):
    pass


class GlobalParamOut(GlobalParamIn):
    id: uuid.UUID


class TrackingIn(Schema):
    source_id: uuid.UUID
    table: str = "events"
    name_column: str = "event_name"
    time_column: str = "event_ts"
    date_column: str = "event_date"
    params_column: str = "params"
    user_column: str = "user_id"
    platform_column: str = "platform"
    version_column: str = "app_version"
    drop_threshold: float = Field(default=0.5, gt=0, lt=1)


class TrackingOut(TrackingIn):
    project_id: uuid.UUID


class ValidationRunOut(Schema):
    id: uuid.UUID
    project_id: uuid.UUID
    started_at: datetime
    data_until: datetime | None
    status: str
    summary: dict[str, Any]
    results: list[dict[str, Any]]
    error: str


class AlertOut(Schema):
    id: uuid.UUID
    project_id: uuid.UUID
    event_id: uuid.UUID | None
    event_name: str
    kind: str
    severity: str
    title: str
    message: str
    details: dict[str, Any]
    status: str
    created_at: datetime
    last_seen_at: datetime
    resolved_at: datetime | None
    acknowledged_by: str


class ImportOut(Schema):
    created: list[str]
    versioned: list[str]
    unchanged: list[str]
    errors: list[str]


class DiscoveredEvent(Schema):
    name: str
    count: int
    registered: bool
    params: list[ParamIn]


class DiscoverApplyIn(Schema):
    project_id: uuid.UUID
    events: list[DiscoveredEvent]


class StatPoint(Schema):
    date: str
    platform: str
    count: int


class Governance(Schema):
    no_owner: list[str]
    no_metrics: list[str]
    deprecated_firing: list[str]
    unregistered: list[str]
    pending_review: list[str]
    stale_drafts: list[str]


class ChannelIn(Schema):
    name: str = Field(min_length=1, max_length=200)
    kind: Literal["slack", "mattermost", "telegram", "email"]
    config: dict[str, Any] = Field(default_factory=dict)
    secrets: dict[str, str] = Field(default_factory=dict)
    min_severity: Literal["warning", "critical"] = "warning"
    project_ids: list[uuid.UUID] | None = None
    enabled: bool = True


class ChannelOut(Schema):
    id: uuid.UUID
    name: str
    kind: str
    config: dict[str, Any]
    min_severity: str
    project_ids: list[uuid.UUID] | None
    enabled: bool
    has_secrets: bool = False
