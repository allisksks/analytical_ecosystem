"""Symmetric encryption of secrets at rest (connector credentials).

Uses Fernet (AES-128-CBC + HMAC-SHA256). The key comes from ENCRYPTION_KEY (or a KMS/Vault-provided
value injected into it). Without it a key is derived from SECRET_KEY, which is acceptable only in dev.
"""

from __future__ import annotations

import base64
import json
from functools import lru_cache
from typing import Any

import structlog
from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from app.core.config import get_settings
from app.core.errors import AppError

log = structlog.get_logger("crypto")


@lru_cache
def _fernet() -> Fernet:
    settings = get_settings()
    if settings.encryption_key and settings.encryption_key.get_secret_value():
        return Fernet(settings.encryption_key.get_secret_value().encode())
    if settings.is_prod:
        log.warning("ENCRYPTION_KEY is not set; deriving it from SECRET_KEY")
    raw = HKDF(algorithm=hashes.SHA256(), length=32, salt=b"analytics-platform", info=b"secrets").derive(
        settings.secret_key.get_secret_value().encode()
    )
    return Fernet(base64.urlsafe_b64encode(raw))


def encrypt_json(data: dict[str, Any]) -> bytes:
    return _fernet().encrypt(json.dumps(data).encode())


def decrypt_json(token: bytes | None) -> dict[str, Any]:
    if not token:
        return {}
    try:
        return json.loads(_fernet().decrypt(token))  # type: ignore[no-any-return]
    except InvalidToken as exc:
        raise AppError("Не удалось расшифровать учётные данные источника (сменился ENCRYPTION_KEY?)") from exc
