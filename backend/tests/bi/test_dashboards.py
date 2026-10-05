from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from httpx import AsyncClient

from app.modules.semantic.service import install_pack
from tests.conftest import World

H = Callable[[str], dict[str, str]]
RANGE = {"date_from": "2026-04-01", "date_to": "2026-05-31"}  # demo_dir ends 2026-05-31


@pytest.fixture
async def ready(world: World, demo_source: Any) -> None:
    await install_pack(world.db, world.org.id, "gaming")
    await world.add_user("lead", "analytics_lead", None)
    await world.add_user("po", "product", ["alpha"])
    await world.add_user("mkt_alpha", "marketing", ["alpha"])
    await world.db.commit()


async def _from_template(client: AsyncClient, hdr: dict[str, str], key: str, project: Any | None) -> dict[str, Any]:
    r = await client.post(
        "/dashboards/from-template",
        json={"template_key": key, "project_id": str(project.id) if project else None},
        headers=hdr,
    )
    assert r.status_code == 201, r.text
    return r.json()


async def test_every_template_widget_returns_data(client: AsyncClient, world: World, as_user: H, ready: None) -> None:
    templates = (await client.get("/dashboards/templates", headers=as_user("lead"))).json()
    assert {t["key"] for t in templates} >= {"overview", "retention", "monetisation", "acquisition", "portfolio"}
    for tpl in templates:
        project = None if tpl["scope"] == "portfolio" else world.projects["alpha"]
        dash = await _from_template(client, as_user("lead"), tpl["key"], project)
        for w in dash["widgets"]:
            r = await client.post(
                f"/dashboards/{dash['id']}/widgets/{w['id']}/data", json=RANGE, headers=as_user("lead")
            )
            assert r.status_code == 200, (tpl["key"], w["title"], r.text)
            assert r.json()["rows"], (tpl["key"], w["title"])


async def test_role_access_to_dashboards(client: AsyncClient, world: World, as_user: H, ready: None) -> None:
    dash = await _from_template(client, as_user("lead"), "overview", world.projects["alpha"])
    assert (await client.get(f"/dashboards/{dash['id']}", headers=as_user("marketing"))).status_code == 404
    r = await client.get(f"/dashboards/{dash['id']}", headers=as_user("po"))
    assert r.status_code == 200
    assert r.json()["can_edit"] is False  # product edits only own dashboards
    assert (
        await client.patch(f"/dashboards/{dash['id']}", json={"title": "x"}, headers=as_user("po"))
    ).status_code == 403
    own = await client.post(
        "/dashboards", json={"project_id": str(world.projects["alpha"].id), "title": "Мой"}, headers=as_user("po")
    )
    assert own.status_code == 201
    assert own.json()["can_edit"] is True

    portfolio = await _from_template(client, as_user("lead"), "portfolio", None)
    assert (await client.get(f"/dashboards/{portfolio['id']}", headers=as_user("analyst"))).status_code == 404
    assert (await client.get(f"/dashboards/{portfolio['id']}", headers=as_user("ceo"))).status_code == 200


async def test_marketing_sees_only_own_project_data(client: AsyncClient, world: World, as_user: H, ready: None) -> None:
    dash = await _from_template(client, as_user("lead"), "acquisition", world.projects["alpha"])
    table = next(w for w in dash["widgets"] if w["viz"] == "table")
    r = await client.post(
        "/widgets/preview",
        json={
            "project_id": str(world.projects["alpha"].id),
            "spec": {"metrics": ["installs"], "dimensions": ["app_id"]},
            **RANGE,
        },
        headers=as_user("mkt_alpha"),
    )
    assert r.status_code == 200, r.text
    assert [row[0] for row in r.json()["rows"]] == ["iron_shells"]
    r = await client.post(
        f"/dashboards/{dash['id']}/widgets/{table['id']}/data", json=RANGE, headers=as_user("mkt_alpha")
    )
    assert r.status_code == 200


async def test_sql_widget_rules_and_date_placeholders(
    client: AsyncClient, world: World, as_user: H, ready: None, demo_source: Any
) -> None:
    alpha = str(world.projects["alpha"].id)
    dash = (
        await client.post("/dashboards", json={"project_id": alpha, "title": "SQL"}, headers=as_user("analyst"))
    ).json()
    spec = {
        "source_id": str(demo_source.id),
        "sql": "SELECT count(*) AS n FROM users WHERE install_date BETWEEN {{date_from}} AND {{date_to}}",
    }
    w = {"title": "n", "viz": "kpi", "mode": "sql", "spec": spec}
    own = (await client.post("/dashboards", json={"project_id": alpha, "title": "PO"}, headers=as_user("po"))).json()
    assert (await client.post(f"/dashboards/{own['id']}/widgets", json=w, headers=as_user("po"))).status_code == 403
    r = await client.post(f"/dashboards/{dash['id']}/widgets", json=w, headers=as_user("analyst"))
    assert r.status_code == 201, r.text
    data = (
        await client.post(f"/dashboards/{dash['id']}/widgets/{r.json()['id']}/data", json=RANGE, headers=as_user("po"))
    ).json()
    assert data["rows"][0][0] > 0
    assert "'2026-04-01'" in data["sql"][0]


async def test_public_link_with_expiry(client: AsyncClient, world: World, as_user: H, ready: None) -> None:
    dash = await _from_template(client, as_user("lead"), "overview", world.projects["alpha"])
    r = await client.post(f"/dashboards/{dash['id']}/share", json={"ttl_days": 1}, headers=as_user("lead"))
    token = r.json()["token"]
    pub = await client.get(f"/public/dashboards/{token}")
    assert pub.status_code == 200
    assert pub.json()["owner_id"] is None
    w = pub.json()["widgets"][0]
    assert (await client.post(f"/public/dashboards/{token}/widgets/{w['id']}/data", json=RANGE)).status_code == 200
    from app.modules.bi.models import Dashboard

    d = await world.db.get(Dashboard, dash["id"])
    assert d is not None
    d.share_expires_at = datetime.now(UTC) - timedelta(minutes=1)
    await world.db.commit()
    assert (await client.get(f"/public/dashboards/{token}")).status_code == 404


async def test_guest_sees_only_granted_dashboard(client: AsyncClient, world: World, as_user: H, ready: None) -> None:
    guest = await world.add_user("guest", "guest", ["alpha"])
    await world.db.commit()
    a = await _from_template(client, as_user("lead"), "overview", world.projects["alpha"])
    b = await _from_template(client, as_user("lead"), "retention", world.projects["alpha"])
    r = await client.post(f"/dashboards/{a['id']}/grants", json={"user_id": str(guest.id)}, headers=as_user("lead"))
    assert r.status_code == 204
    listed = (
        await client.get(
            "/dashboards", params={"project_id": str(world.projects["alpha"].id)}, headers=as_user("guest")
        )
    ).json()
    assert [d["id"] for d in listed] == [a["id"]]
    assert (await client.get(f"/dashboards/{b['id']}", headers=as_user("guest"))).status_code == 404
    w = a["widgets"][0]
    r = await client.post(f"/dashboards/{a['id']}/widgets/{w['id']}/data", json=RANGE, headers=as_user("guest"))
    assert r.status_code == 200, r.text
