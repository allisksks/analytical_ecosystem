"""FastAPI dependencies: resolve the caller (user JWT, OIDC token or service token) into a Principal."""

from __future__ import annotations

import hmac
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from functools import lru_cache
from typing import Annotated, Any

import jwt
from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.db import get_session
from app.core.errors import AuthError
from app.modules.iam import security
from app.modules.iam.models import ServiceToken, User
from app.modules.iam.policy import Principal
from app.modules.iam.service import build_principal, principal_from_token

DB = Annotated[AsyncSession, Depends(get_session)]
_bearer = HTTPBearer(auto_error=False)


def client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else ""


@lru_cache
def _jwks_client() -> jwt.PyJWKClient:
    settings = get_settings()
    if not settings.oidc_jwks_url:
        raise AuthError("OIDC не настроен (OIDC_JWKS_URL)")
    return jwt.PyJWKClient(settings.oidc_jwks_url, cache_keys=True, lifespan=3600)


def _decode_oidc(token: str) -> dict[str, Any]:
    settings = get_settings()
    try:
        key = _jwks_client().get_signing_key_from_jwt(token)
        payload: dict[str, Any] = jwt.decode(
            token,
            key.key,
            algorithms=["RS256", "ES256"],
            audience=settings.oidc_audience,
            issuer=settings.oidc_issuer,
            options={"verify_aud": bool(settings.oidc_audience)},
        )
    except jwt.PyJWTError as exc:
        raise AuthError("Недействительный токен SSO") from exc
    return payload


async def _user_from_oidc(db: AsyncSession, claims: dict[str, Any]) -> User:
    """Finds the user by OIDC subject (or e-mail on first login). Users without roles see nothing until
    an administrator grants access."""
    sub = str(claims["sub"])
    user = (await db.execute(select(User).where(User.external_id == sub))).scalar_one_or_none()
    if user is None:
        email = str(claims.get("email", "")).lower()
        if not email:
            raise AuthError("В токене SSO нет email")
        user = (await db.execute(select(User).where(User.email == email))).scalar_one_or_none()
        if user is None:
            raise AuthError("Пользователь не заведён в платформе, обратитесь к администратору")
        user.external_id = sub
        await db.flush()
    return user


async def _service_token(db: AsyncSession, token: str) -> ServiceToken:
    try:
        prefix = token.removeprefix(security.SERVICE_TOKEN_PREFIX).split("_", 1)[0]
    except IndexError as exc:  # pragma: no cover
        raise AuthError("Недействительный токен") from exc
    digest = security.hash_service_token(token)
    candidates = (await db.execute(select(ServiceToken).where(ServiceToken.prefix == prefix))).scalars().all()
    now = datetime.now(UTC)
    for t in candidates:
        if hmac.compare_digest(t.token_hash, digest):
            if t.revoked_at is not None or t.expires_at < now:
                raise AuthError("Токен отозван или истёк")
            t.last_used_at = now
            return t
    raise AuthError("Недействительный токен")


async def get_principal(
    request: Request,
    db: DB,
    creds: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> Principal:
    if creds is None or not creds.credentials:
        raise AuthError("Требуется вход")
    token = creds.credentials
    ip = client_ip(request)
    if token.startswith(security.SERVICE_TOKEN_PREFIX):
        return principal_from_token(await _service_token(db, token), ip)
    if get_settings().auth_mode == "oidc":
        user = await _user_from_oidc(db, _decode_oidc(token))
    else:
        payload = security.decode_token(token, "access")
        user_or_none = await db.get(User, uuid.UUID(payload["sub"]))
        if user_or_none is None:
            raise AuthError("Пользователь не найден")
        user = user_or_none
    if not user.is_active or (user.access_expires_at and user.access_expires_at < datetime.now(UTC)):
        raise AuthError("Доступ закрыт")
    return build_principal(user, ip)


CurrentPrincipal = Annotated[Principal, Depends(get_principal)]


def require(permission: str) -> Callable[[Principal], Awaitable[Principal]]:
    """Dependency for organisation-level permissions. Project-scoped checks call ``principal.require``
    with the project id of the resource being touched."""

    async def _dep(principal: CurrentPrincipal) -> Principal:
        principal.require(permission)
        return principal

    return _dep
