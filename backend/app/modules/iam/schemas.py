from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import EmailStr, Field, field_validator

from app.core.schemas import Schema


class LoginIn(Schema):
    email: str = Field(max_length=320)
    password: str = Field(min_length=1, max_length=256)


class TokenOut(Schema):
    access_token: str | None = None
    token_type: str = "bearer"
    mfa_required: bool = False
    mfa_setup_required: bool = False
    mfa_token: str | None = None


class MfaCodeIn(Schema):
    mfa_token: str
    code: str = Field(min_length=6, max_length=10)


class MfaTokenIn(Schema):
    mfa_token: str


class MfaSetupOut(Schema):
    secret: str
    otpauth_uri: str


class ProjectOut(Schema):
    id: uuid.UUID
    key: str
    name: str
    group_name: str
    description: str
    data_scope: dict[str, list[Any]]
    archived: bool


class ProjectIn(Schema):
    key: str = Field(pattern=r"^[a-z][a-z0-9_]{1,63}$")
    name: str = Field(min_length=1, max_length=200)
    group_name: str = ""
    description: str = ""
    data_scope: dict[str, list[Any]] = Field(default_factory=dict)


class ProjectPatch(Schema):
    name: str | None = None
    group_name: str | None = None
    description: str | None = None
    data_scope: dict[str, list[Any]] | None = None
    archived: bool | None = None


class RoleOut(Schema):
    id: uuid.UUID
    key: str
    name: str
    description: str
    permissions: list[str]
    is_builtin: bool


class RoleIn(Schema):
    key: str = Field(pattern=r"^[a-z][a-z0-9_]{1,63}$")
    name: str = Field(min_length=1, max_length=120)
    description: str = ""
    permissions: list[str]


class RolePatch(Schema):
    name: str | None = None
    description: str | None = None
    permissions: list[str] | None = None


class MembershipIn(Schema):
    role_key: str
    project_id: uuid.UUID | None = None


class MembershipOut(Schema):
    role_key: str
    role_name: str
    project_id: uuid.UUID | None


class UserOut(Schema):
    id: uuid.UUID
    email: str
    name: str
    is_active: bool
    locale: str
    totp_enabled: bool
    access_expires_at: datetime | None
    last_login_at: datetime | None
    memberships: list[MembershipOut]


class UserIn(Schema):
    email: EmailStr
    name: str = Field(min_length=1, max_length=200)
    password: str | None = Field(default=None, max_length=256)
    access_expires_at: datetime | None = None
    memberships: list[MembershipIn] = Field(default_factory=list)


class UserPatch(Schema):
    name: str | None = None
    is_active: bool | None = None
    access_expires_at: datetime | None = None
    password: str | None = Field(default=None, max_length=256)


class MeOut(Schema):
    user: UserOut
    org_id: uuid.UUID
    org_name: str
    is_admin: bool
    org_permissions: list[str]
    project_permissions: dict[str, list[str]]
    projects: list[ProjectOut]
    ai_enabled: bool


class MePatch(Schema):
    name: str | None = None
    locale: str | None = Field(default=None, pattern=r"^(ru|en)$")


class PasswordChangeIn(Schema):
    current_password: str
    new_password: str = Field(min_length=10, max_length=256)


class ServiceTokenIn(Schema):
    name: str = Field(min_length=1, max_length=200)
    permissions: list[str] = Field(min_length=1)
    project_id: uuid.UUID | None = None
    ttl_days: int = Field(default=90, ge=1, le=365)


class ServiceTokenOut(Schema):
    id: uuid.UUID
    name: str
    prefix: str
    permissions: list[str]
    project_id: uuid.UUID | None
    expires_at: datetime
    last_used_at: datetime | None
    revoked_at: datetime | None
    created_at: datetime


class ServiceTokenCreated(ServiceTokenOut):
    token: str


class PermissionInfo(Schema):
    key: str
    org_level: bool


class AuditOut(Schema):
    id: int
    ts: datetime
    actor_type: str
    actor_label: str
    action: str
    resource_type: str
    resource_id: str
    project_id: uuid.UUID | None
    outcome: str
    ip: str
    sql: str | None
    row_count: int | None
    details: dict[str, Any]

    @field_validator("details", mode="before")
    @classmethod
    def _none_to_dict(cls, v: Any) -> Any:
        return v or {}
