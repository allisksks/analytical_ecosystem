"""IAM use-cases: principal resolution, login with optional TOTP, refresh rotation, provisioning."""

from __future__ import annotations

import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.errors import AuthError, ConflictError, NotFoundError
from app.modules.audit.service import record
from app.modules.iam import security
from app.modules.iam.models import Membership, Organization, Project, RefreshSession, Role, ServiceToken, User
from app.modules.iam.permissions import ADMIN_PERMISSIONS, BUILTIN_ROLES
from app.modules.iam.policy import Principal

MAX_FAILED_LOGINS = 5
LOCKOUT = timedelta(minutes=15)


def build_principal(user: User, ip: str = "") -> Principal:
    org_perms: set[str] = set()
    proj_perms: dict[uuid.UUID, set[str]] = defaultdict(set)
    roles: dict[uuid.UUID | None, list[str]] = defaultdict(list)
    for m in user.memberships:
        roles[m.project_id].append(m.role.key)
        target = org_perms if m.project_id is None else proj_perms[m.project_id]
        target.update(m.role.permissions)
    return Principal(
        id=user.id,
        org_id=user.org_id,
        kind="user",
        label=user.email,
        org_permissions=frozenset(org_perms),
        project_permissions={k: frozenset(v) for k, v in proj_perms.items()},
        roles_by_project={k: tuple(v) for k, v in roles.items()},
        ip=ip,
    )


def principal_from_token(token: ServiceToken, ip: str = "") -> Principal:
    perms = frozenset(token.permissions)
    if token.project_id is None:
        return Principal(token.id, token.org_id, "token", token.name, perms, {}, {None: ("service",)}, ip)
    return Principal(token.id, token.org_id, "token", token.name, frozenset(), {token.project_id: perms}, {}, ip)


def requires_mfa(user: User) -> bool:
    if not get_settings().mfa_required_for_admins:
        return user.totp_enabled
    return user.totp_enabled or any(
        m.project_id is None and set(m.role.permissions) & ADMIN_PERMISSIONS for m in user.memberships
    )


async def get_user(db: AsyncSession, user_id: uuid.UUID) -> User:
    user = await db.get(User, user_id)
    if user is None:
        raise NotFoundError("Пользователь не найден")
    return user


def _ensure_can_login(user: User) -> None:
    now = datetime.now(UTC)
    if not user.is_active:
        raise AuthError("Учётная запись отключена")
    if user.access_expires_at and user.access_expires_at < now:
        raise AuthError("Срок доступа истёк")


@dataclass
class LoginResult:
    user: User
    mfa_token: str | None = None
    mfa_setup_required: bool = False


async def authenticate(db: AsyncSession, email: str, password: str, ip: str) -> LoginResult:
    user = (await db.execute(select(User).where(User.email == email.lower().strip()))).scalar_one_or_none()
    now = datetime.now(UTC)
    if user and user.locked_until and user.locked_until > now:
        await record(
            db,
            "auth.login",
            org_id=user.org_id,
            actor_label=email,
            outcome="denied",
            ip=ip,
            details={"reason": "locked"},
        )
        raise AuthError("Слишком много попыток входа, попробуйте позже")
    if user is None or not security.verify_password(password, user.password_hash):
        if user is not None:
            user.failed_logins += 1
            if user.failed_logins >= MAX_FAILED_LOGINS:
                user.locked_until = now + LOCKOUT
                user.failed_logins = 0
        await record(
            db,
            "auth.login",
            org_id=user.org_id if user else None,
            actor_label=email,
            outcome="denied",
            ip=ip,
            details={"reason": "bad_credentials"},
        )
        await db.commit()
        raise AuthError("Неверный email или пароль")
    _ensure_can_login(user)
    user.failed_logins = 0
    if requires_mfa(user):
        mfa = security.issue_token("mfa", user.id, timedelta(minutes=5), setup=not user.totp_enabled)
        return LoginResult(user, mfa_token=mfa, mfa_setup_required=not user.totp_enabled)
    return LoginResult(user)


async def start_session(db: AsyncSession, user: User, *, ip: str, user_agent: str) -> tuple[str, str, datetime]:
    """Creates a refresh session; returns (access_token, refresh_token, refresh_expiry)."""
    settings = get_settings()
    now = datetime.now(UTC)
    expires = now + timedelta(days=settings.refresh_token_ttl_days)
    session = RefreshSession(user_id=user.id, expires_at=expires, ip=ip, user_agent=user_agent[:400])
    db.add(session)
    await db.flush()
    user.last_login_at = now
    access = security.issue_token(
        "access", user.id, timedelta(minutes=settings.access_token_ttl_minutes), org=str(user.org_id)
    )
    refresh = security.issue_token("refresh", user.id, expires - now, jti=session.id)
    await record(
        db, "auth.login", org_id=user.org_id, actor_label=user.email, ip=ip, resource_type="user", resource_id=user.id
    )
    return access, refresh, expires


async def rotate_refresh(
    db: AsyncSession, refresh_token: str, *, ip: str, user_agent: str
) -> tuple[str, str, datetime]:
    payload = security.decode_token(refresh_token, "refresh")
    session = await db.get(RefreshSession, uuid.UUID(payload["jti"]))
    if session is None:
        raise AuthError("Сессия не найдена")
    now = datetime.now(UTC)
    if session.revoked_at is not None:
        # refresh token reuse => likely theft: revoke every session of the user
        await db.execute(
            update(RefreshSession)
            .where(RefreshSession.user_id == session.user_id, RefreshSession.revoked_at.is_(None))
            .values(revoked_at=now)
        )
        await db.commit()
        raise AuthError("Сессия отозвана")
    if session.expires_at < now:
        raise AuthError("Сессия истекла")
    user = await get_user(db, session.user_id)
    _ensure_can_login(user)
    session.revoked_at = now
    settings = get_settings()
    new_session = RefreshSession(user_id=user.id, expires_at=session.expires_at, ip=ip, user_agent=user_agent[:400])
    db.add(new_session)
    await db.flush()
    session.replaced_by = new_session.id
    access = security.issue_token(
        "access", user.id, timedelta(minutes=settings.access_token_ttl_minutes), org=str(user.org_id)
    )
    refresh = security.issue_token("refresh", user.id, session.expires_at - now, jti=new_session.id)
    return access, refresh, session.expires_at


async def revoke_refresh(db: AsyncSession, refresh_token: str) -> None:
    try:
        payload = security.decode_token(refresh_token, "refresh")
    except AuthError:
        return
    session = await db.get(RefreshSession, uuid.UUID(payload["jti"]))
    if session and session.revoked_at is None:
        session.revoked_at = datetime.now(UTC)


async def ensure_builtin_roles(db: AsyncSession, org_id: uuid.UUID) -> dict[str, Role]:
    existing = {r.key: r for r in (await db.execute(select(Role).where(Role.org_id == org_id))).scalars()}
    for b in BUILTIN_ROLES:
        role = existing.get(b.key)
        if role is None:
            role = Role(org_id=org_id, key=b.key, name=b.name_ru, description=b.description, is_builtin=True)
            db.add(role)
            existing[b.key] = role
        role.permissions = sorted(b.permissions)  # keep built-ins in sync with code
    await db.flush()
    return existing


async def create_organization(db: AsyncSession, name: str, slug: str) -> Organization:
    if (await db.execute(select(Organization).where(Organization.slug == slug))).scalar_one_or_none():
        raise ConflictError("Организация с таким идентификатором уже существует")
    org = Organization(name=name, slug=slug)
    db.add(org)
    await db.flush()
    await ensure_builtin_roles(db, org.id)
    return org


async def create_user(
    db: AsyncSession,
    org_id: uuid.UUID,
    email: str,
    name: str,
    password: str | None,
    *,
    check_strength: bool = True,
) -> User:
    email = email.lower().strip()
    if (await db.execute(select(User).where(User.email == email))).scalar_one_or_none():
        raise ConflictError("Пользователь с таким email уже существует")
    if password and check_strength:
        security.validate_password_strength(password)
    user = User(
        org_id=org_id, email=email, name=name, password_hash=security.hash_password(password) if password else None
    )
    db.add(user)
    await db.flush()
    return user


async def grant(db: AsyncSession, user: User, role: Role, project: Project | None) -> Membership:
    m = Membership(user_id=user.id, role_id=role.id, project_id=project.id if project else None)
    db.add(m)
    await db.flush()
    await db.refresh(user, attribute_names=["memberships"])
    return m


SYSTEM_ID = uuid.UUID(int=0)


def system_principal(org_id: uuid.UUID, label: str = "system") -> Principal:
    """Principal for background jobs (validation, schedules). Data rules still apply via the project scope."""
    from app.modules.iam.permissions import ALL_PERMISSIONS

    return Principal(
        id=SYSTEM_ID,
        org_id=org_id,
        kind="system",
        label=label,
        org_permissions=frozenset(ALL_PERMISSIONS),
        roles_by_project={None: ("system",)},
    )
