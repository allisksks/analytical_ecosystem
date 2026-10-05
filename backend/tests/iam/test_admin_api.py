from __future__ import annotations

from collections.abc import Callable

from httpx import AsyncClient

from tests.conftest import World

H = Callable[[str], dict[str, str]]


async def test_only_admin_manages_users_and_changes_are_audited(client: AsyncClient, world: World, as_user: H) -> None:
    payload = {
        "email": "new@test.io",
        "name": "Newbie",
        "password": "Str0ng-pass-1",
        "memberships": [{"role_key": "product", "project_id": str(world.projects["alpha"].id)}],
    }
    assert (await client.post("/admin/users", json=payload, headers=as_user("analyst"))).status_code == 403
    r = await client.post("/admin/users", json=payload, headers=as_user("admin"))
    assert r.status_code == 201, r.text
    uid = r.json()["id"]
    assert r.json()["memberships"][0]["role_key"] == "product"

    r = await client.put(
        f"/admin/users/{uid}/memberships", json=[{"role_key": "analyst", "project_id": None}], headers=as_user("admin")
    )
    assert r.status_code == 200
    audit = (await client.get("/admin/audit", params={"action": "user."}, headers=as_user("admin"))).json()
    actions = [a["action"] for a in audit["items"]]
    assert actions[:2] == ["user.roles_changed", "user.create"]
    assert audit["items"][0]["details"]["after"] == ["analyst@*"]


async def test_admin_cannot_demote_self(client: AsyncClient, world: World, as_user: H) -> None:
    uid = world.users["admin"].id
    r = await client.put(f"/admin/users/{uid}/memberships", json=[], headers=as_user("admin"))
    assert r.status_code == 409


async def test_projects_visibility_by_membership(client: AsyncClient, world: World, as_user: H) -> None:
    keys = lambda r: sorted(p["key"] for p in r.json())  # noqa: E731
    assert keys(await client.get("/projects", headers=as_user("analyst"))) == ["alpha"]
    assert keys(await client.get("/projects", headers=as_user("marketing"))) == ["beta"]
    assert keys(await client.get("/projects", headers=as_user("ceo"))) == ["alpha", "beta"]


async def test_custom_role_and_validation(client: AsyncClient, world: World, as_user: H) -> None:
    r = await client.post(
        "/admin/roles",
        json={"key": "viewer", "name": "Viewer", "permissions": ["kb:view", "nope:x"]},
        headers=as_user("admin"),
    )
    assert r.status_code == 422
    r = await client.post(
        "/admin/roles", json={"key": "viewer", "name": "Viewer", "permissions": ["kb:view"]}, headers=as_user("admin")
    )
    assert r.status_code == 201
    builtin = next(x for x in (await client.get("/admin/roles", headers=as_user("admin"))).json() if x["is_builtin"])
    assert (
        await client.patch(f"/admin/roles/{builtin['id']}", json={"name": "x"}, headers=as_user("admin"))
    ).status_code == 409


async def test_service_token_scope_and_revocation(client: AsyncClient, world: World, as_user: H) -> None:
    r = await client.post(
        "/admin/tokens",
        json={"name": "ci", "permissions": ["kb:view"], "project_id": str(world.projects["alpha"].id), "ttl_days": 1},
        headers=as_user("admin"),
    )
    assert r.status_code == 201
    token = r.json()["token"]
    assert token.startswith("apt_")
    hdr = {"Authorization": f"Bearer {token}"}
    r = await client.get("/projects", headers=hdr)
    assert [p["key"] for p in r.json()] == ["alpha"]
    assert (await client.get("/admin/users", headers=hdr)).status_code == 403
    token_id = (await client.get("/admin/tokens", headers=as_user("admin"))).json()[0]["id"]
    assert (await client.delete(f"/admin/tokens/{token_id}", headers=as_user("admin"))).status_code == 204
    assert (await client.get("/projects", headers=hdr)).status_code == 401
    assert (
        await client.post("/admin/tokens", json={"name": "x", "permissions": ["admin:users"]}, headers=as_user("admin"))
    ).status_code == 422
