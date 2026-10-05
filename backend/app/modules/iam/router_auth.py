"""Authentication endpoints. Access token in the body, refresh token in an httpOnly cookie."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Cookie, Request, Response
from sqlalchemy import select

from app.core.config import get_settings
from app.core.errors import AuthError
from app.modules.audit.service import record
from app.modules.iam import security
from app.modules.iam.deps import DB, CurrentPrincipal, client_ip
from app.modules.iam.models import Organization, Project, User
from app.modules.iam.schemas import (
    LoginIn,
    MembershipOut,
    MeOut,
    MePatch,
    MfaCodeIn,
    MfaSetupOut,
    MfaTokenIn,
    PasswordChangeIn,
    ProjectOut,
    TokenOut,
    UserOut,
)
from app.modules.iam.service import authenticate, get_user, revoke_refresh, rotate_refresh, start_session

router = APIRouter(prefix="/auth", tags=["auth"])
REFRESH_COOKIE = "ap_refresh"


def _set_refresh_cookie(response: Response, token: str, expires: datetime) -> None:
    settings = get_settings()
    response.set_cookie(
        REFRESH_COOKIE,
        token,
        expires=expires,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="strict",
        path=f"{settings.api_prefix}/auth",
    )


def _clear_refresh_cookie(response: Response) -> None:
    response.delete_cookie(REFRESH_COOKIE, path=f"{get_settings().api_prefix}/auth")


def user_out(user: User) -> UserOut:
    return UserOut(
        id=user.id,
        email=user.email,
        name=user.name,
        is_active=user.is_active,
        locale=user.locale,
        totp_enabled=user.totp_enabled,
        access_expires_at=user.access_expires_at,
        last_login_at=user.last_login_at,
        memberships=[
            MembershipOut(role_key=m.role.key, role_name=m.role.name, project_id=m.project_id) for m in user.memberships
        ],
    )


async def _finish_login(db: DB, user: User, request: Request, response: Response) -> TokenOut:
    access, refresh, expires = await start_session(
        db, user, ip=client_ip(request), user_agent=request.headers.get("user-agent", "")
    )
    await db.commit()
    _set_refresh_cookie(response, refresh, expires)
    return TokenOut(access_token=access)


@router.post("/login", response_model=TokenOut, summary="Sign in with e-mail and password")
async def login(body: LoginIn, request: Request, response: Response, db: DB) -> TokenOut:
    if get_settings().auth_mode == "oidc":
        raise AuthError("Вход выполняется через SSO")
    result = await authenticate(db, body.email, body.password, client_ip(request))
    if result.mfa_token:
        await db.commit()
        return TokenOut(mfa_required=True, mfa_setup_required=result.mfa_setup_required, mfa_token=result.mfa_token)
    return await _finish_login(db, result.user, request, response)


async def _user_from_mfa_token(db: DB, mfa_token: str) -> User:
    payload = security.decode_token(mfa_token, "mfa")
    return await get_user(db, uuid.UUID(payload["sub"]))


@router.post("/mfa/setup", response_model=MfaSetupOut, summary="Start TOTP enrolment (during login)")
async def mfa_setup(body: MfaTokenIn, db: DB) -> MfaSetupOut:
    user = await _user_from_mfa_token(db, body.mfa_token)
    if user.totp_enabled:
        raise AuthError("Второй фактор уже настроен")
    user.totp_secret = security.new_totp_secret()
    await db.commit()
    return MfaSetupOut(
        secret=user.totp_secret, otpauth_uri=security.totp_uri(user.totp_secret, user.email, get_settings().app_name)
    )


@router.post("/mfa/verify", response_model=TokenOut, summary="Complete login with a TOTP code")
async def mfa_verify(body: MfaCodeIn, request: Request, response: Response, db: DB) -> TokenOut:
    user = await _user_from_mfa_token(db, body.mfa_token)
    if not security.verify_totp(user.totp_secret, body.code):
        await record(
            db, "auth.mfa", org_id=user.org_id, actor_label=user.email, outcome="denied", ip=client_ip(request)
        )
        await db.commit()
        raise AuthError("Неверный код")
    if not user.totp_enabled:
        user.totp_enabled = True
        await record(
            db,
            "auth.mfa_enabled",
            org_id=user.org_id,
            actor_label=user.email,
            resource_type="user",
            resource_id=user.id,
        )
    return await _finish_login(db, user, request, response)


@router.post("/refresh", response_model=TokenOut, summary="Exchange the refresh cookie for a new access token")
async def refresh(
    request: Request,
    response: Response,
    db: DB,
    ap_refresh: Annotated[str | None, Cookie()] = None,
) -> TokenOut:
    if not ap_refresh:
        raise AuthError("Нет активной сессии")
    try:
        access, new_refresh, expires = await rotate_refresh(
            db, ap_refresh, ip=client_ip(request), user_agent=request.headers.get("user-agent", "")
        )
    except AuthError:
        _clear_refresh_cookie(response)
        raise
    await db.commit()
    _set_refresh_cookie(response, new_refresh, expires)
    return TokenOut(access_token=access)


@router.post("/logout", status_code=204, summary="Revoke the current session")
async def logout(response: Response, db: DB, ap_refresh: Annotated[str | None, Cookie()] = None) -> Response:
    if ap_refresh:
        await revoke_refresh(db, ap_refresh)
        await db.commit()
    response.status_code = 204
    _clear_refresh_cookie(response)
    return response


@router.get("/me", response_model=MeOut, summary="Current user, permissions and visible projects")
async def me(principal: CurrentPrincipal, db: DB) -> MeOut:
    if principal.kind != "user":
        raise AuthError("Доступно только пользователям")
    user = await get_user(db, principal.id)
    org = await db.get(Organization, principal.org_id)
    assert org is not None
    q = (
        select(Project)
        .where(Project.org_id == principal.org_id, Project.archived.is_(False))
        .order_by(Project.group_name, Project.name)
    )
    visible = principal.visible_project_ids()
    if visible is not None:
        q = q.where(Project.id.in_(visible))
    projects = (await db.execute(q)).scalars().all()
    return MeOut(
        user=user_out(user),
        org_id=org.id,
        org_name=org.name,
        is_admin=principal.is_admin,
        org_permissions=sorted(principal.org_permissions),
        project_permissions={str(p.id): sorted(principal.permissions_in(p.id)) for p in projects},
        projects=[ProjectOut.model_validate(p) for p in projects],
        ai_enabled=get_settings().ai_enabled,
    )


@router.patch("/me", response_model=UserOut, summary="Update own profile")
async def update_me(body: MePatch, principal: CurrentPrincipal, db: DB) -> UserOut:
    user = await get_user(db, principal.id)
    if body.name is not None:
        user.name = body.name
    if body.locale is not None:
        user.locale = body.locale
    await db.commit()
    return user_out(user)


@router.post("/me/password", status_code=204, summary="Change own password")
async def change_password(body: PasswordChangeIn, principal: CurrentPrincipal, db: DB) -> Response:
    user = await get_user(db, principal.id)
    if not security.verify_password(body.current_password, user.password_hash):
        raise AuthError("Текущий пароль указан неверно")
    security.validate_password_strength(body.new_password)
    user.password_hash = security.hash_password(body.new_password)
    await record(db, "auth.password_changed", principal=principal, resource_type="user", resource_id=user.id)
    await db.commit()
    return Response(status_code=204)
