from __future__ import annotations

from collections.abc import Callable
from typing import Any

from httpx import AsyncClient

from tests.conftest import World

H = Callable[[str], dict[str, str]]


def _run(source: Any, project: Any, sql: str) -> dict[str, Any]:
    return {"source_id": str(source.id), "project_id": str(project.id) if project else None, "sql": sql}


async def test_analyst_sees_only_project_rows_and_masked_pii(
    client: AsyncClient, world: World, as_user: H, demo_source: Any
) -> None:
    alpha = world.projects["alpha"]
    r = await client.post(
        "/query/run", json=_run(demo_source, alpha, "SELECT DISTINCT app_id FROM users"), headers=as_user("analyst")
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["rows"] == [["iron_shells"]]
    assert "users.app_id" in body["filtered_columns"]

    r = await client.post(
        "/query/run", json=_run(demo_source, alpha, "SELECT device_id FROM users LIMIT 3"), headers=as_user("analyst")
    )
    assert all(len(row[0]) == 32 and not row[0].startswith("dev_") for row in r.json()["rows"])
    assert r.json()["masked_columns"] == ["users.device_id"]


async def test_data_engineer_sees_raw_pii(client: AsyncClient, world: World, as_user: H, demo_source: Any) -> None:
    await world.add_user("engineer", "data_engineer", ["alpha"])
    await world.db.commit()
    r = await client.post(
        "/query/run",
        json=_run(demo_source, world.projects["alpha"], "SELECT device_id FROM users LIMIT 1"),
        headers=as_user("engineer"),
    )
    assert r.json()["rows"][0][0].startswith("dev_")


async def test_role_model_blocks_foreign_projects(
    client: AsyncClient, world: World, as_user: H, demo_source: Any
) -> None:
    # marketing has no sql:run at all; analyst is not a member of beta
    r = await client.post(
        "/query/run",
        json=_run(demo_source, world.projects["beta"], "SELECT 1 AS x FROM users"),
        headers=as_user("analyst"),
    )
    assert r.status_code == 404  # project is invisible
    r = await client.post(
        "/query/run",
        json=_run(demo_source, world.projects["beta"], "SELECT 1 AS x FROM users"),
        headers=as_user("marketing"),
    )
    assert r.status_code == 403
    r = await client.post(
        "/query/run", json=_run(demo_source, None, "SELECT 1 AS x FROM users"), headers=as_user("analyst")
    )
    assert r.status_code == 403


async def test_rejected_query_is_audited(client: AsyncClient, world: World, as_user: H, demo_source: Any) -> None:
    r = await client.post(
        "/query/run", json=_run(demo_source, world.projects["alpha"], "DELETE FROM users"), headers=as_user("analyst")
    )
    assert r.status_code == 422
    assert r.json()["type"] == "query_rejected"
    audit = (await client.get("/admin/audit", params={"action": "query."}, headers=as_user("admin"))).json()
    assert audit["items"][0]["action"] == "query.rejected"
    assert audit["items"][0]["outcome"] == "denied"


async def test_limit_truncation_cache_history_and_export(
    client: AsyncClient, world: World, as_user: H, demo_source: Any
) -> None:
    payload = {**_run(demo_source, world.projects["alpha"], "SELECT user_id FROM users ORDER BY user_id"), "limit": 5}
    first = (await client.post("/query/run", json=payload, headers=as_user("analyst"))).json()
    assert first["row_count"] == 5
    assert first["truncated"] is True
    assert first["cached"] is False
    second = (await client.post("/query/run", json=payload, headers=as_user("analyst"))).json()
    assert second["cached"] is True
    assert second["rows"] == first["rows"]

    hist = (await client.get("/query/history", headers=as_user("analyst"))).json()
    assert len(hist) == 2

    r = await client.post("/query/export", json={**payload, "format": "csv"}, headers=as_user("analyst"))
    assert r.status_code == 200
    lines = r.content.decode("utf-8-sig").strip().splitlines()
    assert lines[0] == "user_id"
    assert len(lines) > 6  # export ignores the editor limit
    r = await client.post("/query/export", json={**payload, "format": "xlsx"}, headers=as_user("analyst"))
    assert r.content[:2] == b"PK"


async def test_extra_rls_rule_for_role(client: AsyncClient, world: World, as_user: H, demo_source: Any) -> None:
    r = await client.post(
        "/admin/rls-rules",
        json={"column": "platform", "values": ["ios"], "role_key": "analyst"},
        headers=as_user("admin"),
    )
    assert r.status_code == 201
    r = await client.post(
        "/query/run",
        json=_run(demo_source, world.projects["alpha"], "SELECT DISTINCT platform FROM users"),
        headers=as_user("analyst"),
    )
    assert r.json()["rows"] == [["ios"]]


async def test_saved_queries(client: AsyncClient, world: World, as_user: H, demo_source: Any) -> None:
    body = {
        "name": "DAU",
        "sql": "SELECT 1",
        "source_id": str(demo_source.id),
        "project_id": str(world.projects["alpha"].id),
    }
    r = await client.post("/saved-queries", json=body, headers=as_user("analyst"))
    assert r.status_code == 201
    listed = (await client.get("/saved-queries", headers=as_user("analyst"))).json()
    assert [q["name"] for q in listed] == ["DAU"]
    assert (await client.get("/saved-queries", headers=as_user("marketing"))).json() == []
