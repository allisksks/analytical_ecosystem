from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from httpx import AsyncClient
from sqlalchemy import select

from app.modules.connectors.models import DataSource
from tests.conftest import World

H = Callable[[str], dict[str, str]]
PG = {
    "host": "localhost",
    "port": 55432,
    "database": "postgres",
    "user": "postgres",
    "password": "pg",
    "sslmode": "disable",
}


async def test_types_include_planned(client: AsyncClient, world: World, as_user: H) -> None:
    types = (await client.get("/connectors/types", headers=as_user("analyst"))).json()
    by_type = {t["type"]: t for t in types}
    assert by_type["clickhouse"]["available"] and by_type["clickhouse"]["config_schema"]["properties"]["host"]
    assert by_type["bigquery"]["available"] is False


async def test_secrets_are_encrypted_and_never_returned(client: AsyncClient, world: World, as_user: H) -> None:
    r = await client.post("/sources", json={"name": "pg", "type": "postgres", "config": PG}, headers=as_user("analyst"))
    assert r.status_code == 403
    r = await client.post("/sources", json={"name": "pg", "type": "postgres", "config": PG}, headers=as_user("admin"))
    assert r.status_code == 201, r.text
    src = r.json()
    assert src["config"]["password"] == "••••••"
    row = (await world.db.execute(select(DataSource))).scalar_one()
    assert "password" not in row.config
    assert b"pg" not in (row.secrets_encrypted or b"")
    # update without password keeps the stored one
    r = await client.patch(f"/sources/{src['id']}", json={"config": {**PG, "password": ""}}, headers=as_user("admin"))
    assert r.status_code == 200
    r = await client.post(f"/sources/{src['id']}/test", headers=as_user("admin"))
    assert r.json()["ok"] is True, r.text
    assert "PostgreSQL" in r.json()["server_version"]


async def test_connection_check_reports_errors(client: AsyncClient, world: World, as_user: H) -> None:
    r = await client.post(
        "/sources/test", json={"type": "postgres", "config": {**PG, "password": "wrong"}}, headers=as_user("admin")
    )
    assert r.status_code == 200
    assert r.json()["ok"] is False
    assert "password" in r.json()["message"].lower()
    r = await client.post("/sources/test", json={"type": "postgres", "config": {"host": "x"}}, headers=as_user("admin"))
    assert r.status_code == 422


async def test_file_upload_and_catalog_curation(
    client: AsyncClient, world: World, as_user: H, tmp_path: Path, monkeypatch: Any
) -> None:
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "storage_dir", str(tmp_path))
    r = await client.post("/sources", json={"name": "uploads", "type": "files", "config": {}}, headers=as_user("admin"))
    sid = r.json()["id"]
    csv = "user_id,email,amount\nu1,a@b.c,10\nu2,c@d.e,20\n"
    r = await client.post(
        f"/sources/{sid}/files", files={"file": ("Payments 2026.csv", csv, "text/csv")}, headers=as_user("admin")
    )
    assert r.status_code == 200, r.text
    assert r.json()["tables"] == 1
    bad = await client.post(
        f"/sources/{sid}/files", files={"file": ("x.exe", b"MZ", "application/octet-stream")}, headers=as_user("admin")
    )
    assert bad.status_code == 422
    cat = (await client.get(f"/sources/{sid}/catalog", headers=as_user("admin"))).json()
    assert cat[0]["name"] == "payments_2026"
    email = next(c for c in cat[0]["columns"] if c["name"] == "email")
    assert email["is_pii"] is True  # guessed from the name
    r = await client.patch(
        f"/catalog/tables/{cat[0]['id']}", json={"description": "Платежи"}, headers=as_user("analyst")
    )
    assert r.status_code == 200  # catalog:edit in a project that can use the (org-wide) source
    r = await client.patch(f"/catalog/columns/{email['id']}", json={"is_pii": False}, headers=as_user("analyst"))
    assert r.status_code == 403
