from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from httpx import AsyncClient
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.modules.iam import deps
from app.modules.iam.bootstrap import bootstrap
from app.modules.iam.models import Project, User
from tests.conftest import World


async def test_bootstrap_creates_admin_and_demo(db: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    s = get_settings()
    monkeypatch.setattr(s, "bootstrap_admin_password", SecretStr("Admin-pass-123"))
    monkeypatch.setattr(s, "bootstrap_admin_email", "boss@demo.io")
    monkeypatch.setattr(s, "bootstrap_demo", True)
    await bootstrap(db)
    await bootstrap(db)  # idempotent
    emails = set((await db.execute(select(User.email))).scalars())
    assert {"boss@demo.io", "marketing@demo.io", "ceo@demo.io"} <= emails
    keys = set((await db.execute(select(Project.key))).scalars())
    assert keys == {"iron_shells", "bloom_merge", "drift_kings"}


async def test_oidc_tokens_are_verified_against_jwks(
    client: AsyncClient, world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    s = get_settings()
    monkeypatch.setattr(s, "auth_mode", "oidc")
    monkeypatch.setattr(s, "oidc_issuer", "https://kc/realms/x")
    monkeypatch.setattr(s, "oidc_audience", "platform")
    fake = SimpleNamespace(get_signing_key_from_jwt=lambda _t: SimpleNamespace(key=key.public_key()))
    monkeypatch.setattr(deps, "_jwks_client", lambda: fake)
    now = datetime.now(UTC)
    claims = {
        "sub": "kc-123",
        "email": "analyst@test.io",
        "iss": "https://kc/realms/x",
        "aud": "platform",
        "iat": now,
        "exp": now + timedelta(minutes=5),
    }
    token = jwt.encode(claims, key, algorithm="RS256")
    r = await client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200, r.text
    assert r.json()["user"]["email"] == "analyst@test.io"

    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    forged = jwt.encode(claims, other, algorithm="RS256")
    assert (await client.get("/auth/me", headers={"Authorization": f"Bearer {forged}"})).status_code == 401
    unknown = jwt.encode({**claims, "sub": "kc-999", "email": "nobody@test.io"}, key, algorithm="RS256")
    assert (await client.get("/auth/me", headers={"Authorization": f"Bearer {unknown}"})).status_code == 401
