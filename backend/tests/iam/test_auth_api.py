from __future__ import annotations

import pyotp
from httpx import AsyncClient

from tests.conftest import World


async def test_login_refresh_logout_flow(client: AsyncClient, world: World) -> None:
    r = await client.post("/auth/login", json={"email": "analyst@test.io", "password": "Passw0rd-123"})
    assert r.status_code == 200, r.text
    access = r.json()["access_token"]
    assert "ap_refresh" in r.cookies
    assert "httponly" in r.headers["set-cookie"].lower()

    me = await client.get("/auth/me", headers={"Authorization": f"Bearer {access}"})
    assert me.status_code == 200
    body = me.json()
    assert body["user"]["email"] == "analyst@test.io"
    assert [p["key"] for p in body["projects"]] == ["alpha"]
    assert "sql:run" in body["project_permissions"][str(world.projects["alpha"].id)]

    old_refresh = client.cookies.get("ap_refresh")
    r = await client.post("/auth/refresh")
    assert r.status_code == 200 and r.json()["access_token"]
    # reuse of a rotated refresh token revokes all sessions
    client.cookies.set("ap_refresh", old_refresh, path="/api/v1/auth")
    assert (await client.post("/auth/refresh")).status_code == 401
    assert (await client.post("/auth/refresh")).status_code == 401

    r = await client.post("/auth/logout")
    assert r.status_code == 204


async def test_bad_password_and_lockout(client: AsyncClient, world: World) -> None:
    for _ in range(5):
        r = await client.post("/auth/login", json={"email": "analyst@test.io", "password": "wrong"})
        assert r.status_code == 401
        assert r.headers["content-type"].startswith("application/problem+json")
    r = await client.post("/auth/login", json={"email": "analyst@test.io", "password": "Passw0rd-123"})
    assert r.status_code == 401
    assert "попыток" in r.json()["title"]


async def test_admin_must_enroll_totp(client: AsyncClient, world: World) -> None:
    r = await client.post("/auth/login", json={"email": "admin@test.io", "password": "Passw0rd-123"})
    body = r.json()
    assert body["mfa_required"] and body["mfa_setup_required"] and body["access_token"] is None
    setup = (await client.post("/auth/mfa/setup", json={"mfa_token": body["mfa_token"]})).json()
    assert setup["otpauth_uri"].startswith("otpauth://totp/")
    bad = await client.post("/auth/mfa/verify", json={"mfa_token": body["mfa_token"], "code": "000000"})
    assert bad.status_code == 401
    code = pyotp.TOTP(setup["secret"]).now()
    ok = await client.post("/auth/mfa/verify", json={"mfa_token": body["mfa_token"], "code": code})
    assert ok.status_code == 200 and ok.json()["access_token"]
    # next login asks for the code, no enrolment
    r = await client.post("/auth/login", json={"email": "admin@test.io", "password": "Passw0rd-123"})
    assert r.json()["mfa_required"] and not r.json()["mfa_setup_required"]


async def test_requests_without_token_are_rejected(client: AsyncClient, world: World) -> None:
    r = await client.get("/auth/me")
    assert r.status_code == 401
    r = await client.get("/auth/me", headers={"Authorization": "Bearer garbage"})
    assert r.status_code == 401
