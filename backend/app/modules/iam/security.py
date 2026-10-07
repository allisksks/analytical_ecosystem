"""Credentials: password hashing, JWT issue/verify, TOTP, service-token hashing."""

from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

import jwt
import pyotp
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

from app.core.config import get_settings
from app.core.errors import AuthError

_hasher = PasswordHasher()
ALGORITHM = "HS256"
ISSUER = "analytics-platform"
TokenType = Literal["access", "refresh", "mfa"]

# Pre-computed hash to keep login timing equal for unknown users.
_DUMMY_HASH = _hasher.hash("dummy-password-for-timing")


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str | None) -> bool:
    try:
        return _hasher.verify(password_hash or _DUMMY_HASH, password) and password_hash is not None
    except (VerifyMismatchError, InvalidHashError):
        return False


def validate_password_strength(password: str) -> None:
    if len(password) < 10 or password.isdigit() or password.isalpha() or password.lower() == password.upper():
        raise AuthError("Пароль должен быть не короче 10 символов и содержать буквы и цифры")


def _secret() -> str:
    return get_settings().secret_key.get_secret_value()


def issue_token(
    typ: TokenType, subject: uuid.UUID, ttl: timedelta, *, jti: uuid.UUID | None = None, **claims: Any
) -> str:
    now = datetime.now(UTC)
    payload: dict[str, Any] = {
        "iss": ISSUER,
        "sub": str(subject),
        "typ": typ,
        "iat": now,
        "exp": now + ttl,
        "jti": str(jti or uuid.uuid4()),
        **claims,
    }
    return jwt.encode(payload, _secret(), algorithm=ALGORITHM)


def decode_token(token: str, expected: TokenType) -> dict[str, Any]:
    try:
        payload: dict[str, Any] = jwt.decode(
            token, _secret(), algorithms=[ALGORITHM], issuer=ISSUER, options={"require": ["exp", "sub", "typ"]}
        )
    except jwt.ExpiredSignatureError as exc:
        raise AuthError("Срок действия токена истёк") from exc
    except jwt.PyJWTError as exc:
        raise AuthError("Недействительный токен") from exc
    if payload.get("typ") != expected:
        raise AuthError("Неверный тип токена")
    return payload


def new_totp_secret() -> str:
    return pyotp.random_base32()


def totp_uri(secret: str, email: str, issuer: str) -> str:
    return pyotp.TOTP(secret).provisioning_uri(name=email, issuer_name=issuer)


def verify_totp(secret: str | None, code: str) -> bool:
    if not secret:
        return False
    return pyotp.TOTP(secret).verify(code.strip().replace(" ", ""), valid_window=1)


SERVICE_TOKEN_PREFIX = "apt_"


def new_service_token() -> tuple[str, str, str]:
    """Returns (plain token shown once, lookup prefix, sha256 hash stored in DB)."""
    prefix = secrets.token_hex(4)
    token = f"{SERVICE_TOKEN_PREFIX}{prefix}_{secrets.token_urlsafe(32)}"
    return token, prefix, hash_service_token(token)


def hash_service_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()
