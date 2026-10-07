"""Administration: projects, users and their roles, custom roles, service tokens, audit journal."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import delete, func, select

from app.core.errors import ConflictError, NotFoundError, ValidationFailed
from app.core.schemas import Page
from app.modules.audit.models import AuditLog
from app.modules.audit.service import record
from app.modules.iam import security
from app.modules.iam.deps import DB, CurrentPrincipal, require
from app.modules.iam.models import Membership, Project, Role, ServiceToken, User
from app.modules.iam.permissions import ALL_PERMISSIONS, ORG_LEVEL, P
from app.modules.iam.policy import Principal
from app.modules.iam.router_auth import user_out
from app.modules.iam.schemas import (
    AuditOut,
    MembershipIn,
    PermissionInfo,
    ProjectIn,
    ProjectOut,
    ProjectPatch,
    RoleIn,
    RoleOut,
    RolePatch,
    ServiceTokenCreated,
    ServiceTokenIn,
    ServiceTokenOut,
    UserIn,
    UserOut,
    UserPatch,
)
from app.modules.iam.service import create_user

router = APIRouter(tags=["admin"])

UsersAdmin = Annotated[Principal, Depends(require(P.ADMIN_USERS))]
RolesAdmin = Annotated[Principal, Depends(require(P.ADMIN_ROLES))]
ProjectsAdmin = Annotated[Principal, Depends(require(P.ADMIN_PROJECTS))]
TokensAdmin = Annotated[Principal, Depends(require(P.ADMIN_TOKENS))]
AuditAdmin = Annotated[Principal, Depends(require(P.ADMIN_AUDIT))]


# ---------------------------------------------------------------- projects
async def get_project(db: DB, principal: Principal, project_id: uuid.UUID) -> Project:
    project = await db.get(Project, project_id)
    visible = principal.visible_project_ids()
    if project is None or project.org_id != principal.org_id or (visible is not None and project.id not in visible):
        raise NotFoundError("Проект не найден")
    return project


@router.get("/projects", response_model=list[ProjectOut], summary="Projects visible to the caller")
async def list_projects(principal: CurrentPrincipal, db: DB, include_archived: bool = False) -> list[Project]:
    q = select(Project).where(Project.org_id == principal.org_id).order_by(Project.group_name, Project.name)
    if not include_archived:
        q = q.where(Project.archived.is_(False))
    visible = principal.visible_project_ids()
    if visible is not None:
        q = q.where(Project.id.in_(visible))
    return list((await db.execute(q)).scalars())


@router.post("/projects", response_model=ProjectOut, status_code=201)
async def create_project(body: ProjectIn, principal: ProjectsAdmin, db: DB) -> Project:
    exists = await db.scalar(select(Project.id).where(Project.org_id == principal.org_id, Project.key == body.key))
    if exists:
        raise ConflictError("Проект с таким ключом уже существует")
    project = Project(org_id=principal.org_id, **body.model_dump())
    db.add(project)
    await db.flush()
    await record(
        db,
        "project.create",
        principal=principal,
        resource_type="project",
        resource_id=project.id,
        details=body.model_dump(),
    )
    await db.commit()
    return project


@router.patch("/projects/{project_id}", response_model=ProjectOut)
async def update_project(project_id: uuid.UUID, body: ProjectPatch, principal: ProjectsAdmin, db: DB) -> Project:
    project = await get_project(db, principal, project_id)
    changes = body.model_dump(exclude_unset=True)
    for k, v in changes.items():
        setattr(project, k, v)
    # data_scope drives row-level security, so its change is a permission change
    await record(
        db,
        "project.update",
        principal=principal,
        resource_type="project",
        resource_id=project.id,
        project_id=project.id,
        details={"changes": changes},
    )
    await db.commit()
    return project


# ---------------------------------------------------------------- roles
@router.get("/admin/permissions", response_model=list[PermissionInfo])
async def list_permissions(_: CurrentPrincipal) -> list[PermissionInfo]:
    return [PermissionInfo(key=p, org_level=p in ORG_LEVEL) for p in sorted(ALL_PERMISSIONS)]


@router.get("/admin/roles", response_model=list[RoleOut])
async def list_roles(principal: CurrentPrincipal, db: DB) -> list[Role]:
    if not principal.can(P.ADMIN_ROLES):
        principal.require(P.ADMIN_USERS)
    q = select(Role).where(Role.org_id == principal.org_id).order_by(Role.is_builtin.desc(), Role.name)
    return list((await db.execute(q)).scalars())


def _validate_permissions(perms: list[str]) -> list[str]:
    unknown = sorted(set(perms) - ALL_PERMISSIONS)
    if unknown:
        raise ValidationFailed("Неизвестные разрешения", details={"unknown": unknown})
    return sorted(set(perms))


@router.post("/admin/roles", response_model=RoleOut, status_code=201)
async def create_role(body: RoleIn, principal: RolesAdmin, db: DB) -> Role:
    if await db.scalar(select(Role.id).where(Role.org_id == principal.org_id, Role.key == body.key)):
        raise ConflictError("Роль с таким ключом уже существует")
    role = Role(
        org_id=principal.org_id,
        key=body.key,
        name=body.name,
        description=body.description,
        permissions=_validate_permissions(body.permissions),
    )
    db.add(role)
    await db.flush()
    await record(
        db,
        "role.create",
        principal=principal,
        resource_type="role",
        resource_id=role.id,
        details={"permissions": role.permissions},
    )
    await db.commit()
    return role


async def _custom_role(db: DB, principal: Principal, role_id: uuid.UUID) -> Role:
    role = await db.get(Role, role_id)
    if role is None or role.org_id != principal.org_id:
        raise NotFoundError("Роль не найдена")
    if role.is_builtin:
        raise ConflictError("Предустановленные роли не редактируются — создайте свою на их основе")
    return role


@router.patch("/admin/roles/{role_id}", response_model=RoleOut)
async def update_role(role_id: uuid.UUID, body: RolePatch, principal: RolesAdmin, db: DB) -> Role:
    role = await _custom_role(db, principal, role_id)
    if body.name is not None:
        role.name = body.name
    if body.description is not None:
        role.description = body.description
    if body.permissions is not None:
        role.permissions = _validate_permissions(body.permissions)
    await record(
        db,
        "role.update",
        principal=principal,
        resource_type="role",
        resource_id=role.id,
        details=body.model_dump(exclude_unset=True),
    )
    await db.commit()
    return role


@router.delete("/admin/roles/{role_id}", status_code=204)
async def delete_role(role_id: uuid.UUID, principal: RolesAdmin, db: DB) -> Response:
    role = await _custom_role(db, principal, role_id)
    if await db.scalar(select(func.count()).select_from(Membership).where(Membership.role_id == role.id)):
        raise ConflictError("Роль назначена пользователям")
    await db.delete(role)
    await record(db, "role.delete", principal=principal, resource_type="role", resource_id=role_id)
    await db.commit()
    return Response(status_code=204)


# ---------------------------------------------------------------- users
async def _org_user(db: DB, principal: Principal, user_id: uuid.UUID) -> User:
    user = await db.get(User, user_id)
    if user is None or user.org_id != principal.org_id:
        raise NotFoundError("Пользователь не найден")
    return user


async def _apply_memberships(db: DB, principal: Principal, user: User, items: list[MembershipIn]) -> None:
    roles = {r.key: r for r in (await db.execute(select(Role).where(Role.org_id == principal.org_id))).scalars()}
    project_ids = {
        p for p in (await db.execute(select(Project.id).where(Project.org_id == principal.org_id))).scalars()
    }
    seen: set[tuple[str, uuid.UUID | None]] = set()
    await db.execute(delete(Membership).where(Membership.user_id == user.id))
    for item in items:
        role = roles.get(item.role_key)
        if role is None:
            raise ValidationFailed(f"Роль {item.role_key} не найдена")
        if item.project_id is not None and item.project_id not in project_ids:
            raise ValidationFailed("Проект не найден")
        if (item.role_key, item.project_id) in seen:
            continue
        seen.add((item.role_key, item.project_id))
        db.add(Membership(user_id=user.id, role_id=role.id, project_id=item.project_id))
    await db.flush()
    await db.refresh(user, attribute_names=["memberships"])


@router.get("/admin/users", response_model=list[UserOut])
async def list_users(principal: UsersAdmin, db: DB, q: str | None = None) -> list[UserOut]:
    stmt = select(User).where(User.org_id == principal.org_id).order_by(User.name)
    if q:
        stmt = stmt.where(User.email.ilike(f"%{q}%") | User.name.ilike(f"%{q}%"))
    return [user_out(u) for u in (await db.execute(stmt)).scalars()]


@router.post("/admin/users", response_model=UserOut, status_code=201)
async def create_org_user(body: UserIn, principal: UsersAdmin, db: DB) -> UserOut:
    user = await create_user(db, principal.org_id, str(body.email), body.name, body.password)
    user.access_expires_at = body.access_expires_at
    await _apply_memberships(db, principal, user, body.memberships)
    await record(
        db,
        "user.create",
        principal=principal,
        resource_type="user",
        resource_id=user.id,
        details={"email": user.email, "memberships": [m.model_dump(mode="json") for m in body.memberships]},
    )
    await db.commit()
    return user_out(user)


@router.patch("/admin/users/{user_id}", response_model=UserOut)
async def update_org_user(user_id: uuid.UUID, body: UserPatch, principal: UsersAdmin, db: DB) -> UserOut:
    user = await _org_user(db, principal, user_id)
    changes = body.model_dump(exclude_unset=True, exclude={"password"})
    for k, v in changes.items():
        setattr(user, k, v)
    if body.password:
        security.validate_password_strength(body.password)
        user.password_hash = security.hash_password(body.password)
        changes["password"] = "***"
    await record(
        db,
        "user.update",
        principal=principal,
        resource_type="user",
        resource_id=user.id,
        details={"changes": {k: str(v) for k, v in changes.items()}},
    )
    await db.commit()
    return user_out(user)


@router.put("/admin/users/{user_id}/memberships", response_model=UserOut, summary="Replace roles of a user")
async def set_memberships(user_id: uuid.UUID, body: list[MembershipIn], principal: UsersAdmin, db: DB) -> UserOut:
    user = await _org_user(db, principal, user_id)
    if user.id == principal.id and not any(m.role_key == "admin" and m.project_id is None for m in body):
        raise ConflictError("Нельзя снять с себя роль администратора")
    before = [f"{m.role.key}@{m.project_id or '*'}" for m in user.memberships]
    await _apply_memberships(db, principal, user, body)
    after = [f"{m.role.key}@{m.project_id or '*'}" for m in user.memberships]
    await record(
        db,
        "user.roles_changed",
        principal=principal,
        resource_type="user",
        resource_id=user.id,
        details={"before": before, "after": after},
    )
    await db.commit()
    return user_out(user)


@router.post("/admin/users/{user_id}/reset-mfa", response_model=UserOut)
async def reset_mfa(user_id: uuid.UUID, principal: UsersAdmin, db: DB) -> UserOut:
    user = await _org_user(db, principal, user_id)
    user.totp_enabled = False
    user.totp_secret = None
    await record(db, "user.mfa_reset", principal=principal, resource_type="user", resource_id=user.id)
    await db.commit()
    return user_out(user)


# ---------------------------------------------------------------- service tokens
@router.get("/admin/tokens", response_model=list[ServiceTokenOut])
async def list_tokens(principal: TokensAdmin, db: DB) -> list[ServiceToken]:
    q = select(ServiceToken).where(ServiceToken.org_id == principal.org_id).order_by(ServiceToken.created_at.desc())
    return list((await db.execute(q)).scalars())


@router.post("/admin/tokens", response_model=ServiceTokenCreated, status_code=201)
async def create_token(body: ServiceTokenIn, principal: TokensAdmin, db: DB) -> ServiceTokenCreated:
    perms = _validate_permissions(body.permissions)
    if any(p.startswith("admin:") for p in perms):
        raise ValidationFailed("Сервисным токенам нельзя выдавать административные права")
    plain, prefix, digest = security.new_service_token()
    token = ServiceToken(
        org_id=principal.org_id,
        name=body.name,
        prefix=prefix,
        token_hash=digest,
        permissions=perms,
        project_id=body.project_id,
        expires_at=datetime.now(UTC) + timedelta(days=body.ttl_days),
        created_by=principal.id,
    )
    db.add(token)
    await db.flush()
    await db.refresh(token)
    await record(
        db,
        "token.create",
        principal=principal,
        resource_type="service_token",
        resource_id=token.id,
        project_id=body.project_id,
        details={"permissions": perms, "ttl_days": body.ttl_days},
    )
    await db.commit()
    return ServiceTokenCreated(**ServiceTokenOut.model_validate(token).model_dump(), token=plain)


@router.delete("/admin/tokens/{token_id}", status_code=204)
async def revoke_token(token_id: uuid.UUID, principal: TokensAdmin, db: DB) -> Response:
    token = await db.get(ServiceToken, token_id)
    if token is None or token.org_id != principal.org_id:
        raise NotFoundError("Токен не найден")
    token.revoked_at = datetime.now(UTC)
    await record(db, "token.revoke", principal=principal, resource_type="service_token", resource_id=token.id)
    await db.commit()
    return Response(status_code=204)


# ---------------------------------------------------------------- audit
@router.get("/admin/audit", response_model=Page[AuditOut])
async def list_audit(
    principal: AuditAdmin,
    db: DB,
    action: str | None = None,
    actor: str | None = None,
    outcome: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[AuditOut]:
    cond = [AuditLog.org_id == principal.org_id]
    if action:
        cond.append(AuditLog.action.startswith(action))
    if actor:
        cond.append(AuditLog.actor_label.ilike(f"%{actor}%"))
    if outcome:
        cond.append(AuditLog.outcome == outcome)
    if since:
        cond.append(AuditLog.ts >= since)
    if until:
        cond.append(AuditLog.ts < until)
    total = await db.scalar(select(func.count()).select_from(AuditLog).where(*cond)) or 0
    rows = (
        await db.execute(select(AuditLog).where(*cond).order_by(AuditLog.id.desc()).limit(limit).offset(offset))
    ).scalars()
    return Page(items=[AuditOut.model_validate(r) for r in rows], total=total)
