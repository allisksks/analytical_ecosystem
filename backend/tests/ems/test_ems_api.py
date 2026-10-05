from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.core.crypto import encrypt_json
from app.modules.connectors.models import DataSource
from app.modules.connectors.service import refresh_catalog
from app.modules.ems.models import NotificationChannel
from app.modules.ems.notify import Notifier
from tests.conftest import World

H = Callable[[str], dict[str, str]]


@pytest.fixture
async def ems(world: World, demo_dir_full: Path) -> dict[str, Any]:
    world.projects["alpha"].data_scope = {"app_id": ["iron_shells"]}
    src = DataSource(org_id=world.org.id, name="events", type="files", config={"path": str(demo_dir_full)})
    world.db.add(src)
    await world.db.flush()
    await refresh_catalog(world.db, src)
    await world.add_user("lead", "analytics_lead", None)
    await world.add_user("dev", "developer", ["alpha"])
    await world.db.commit()
    return {"source": src, "alpha": str(world.projects["alpha"].id)}


async def _create(
    client: AsyncClient, hdr: dict[str, str], project: str, name: str, params: list[dict[str, Any]]
) -> dict[str, Any]:
    r = await client.post(
        "/ems/events", json={"project_id": project, "name": name, "description": name, "params": params}, headers=hdr
    )
    assert r.status_code == 201, r.text
    return r.json()


async def test_lifecycle_with_approval_and_diff(
    client: AsyncClient, world: World, as_user: H, ems: dict[str, Any]
) -> None:
    ev = await _create(
        client, as_user("analyst"), ems["alpha"], "level_complete", [{"name": "level", "type": "int", "required": True}]
    )
    assert ev["status"] == "draft"
    assert ev["versions"][0]["version"] == "1.0.0"
    v1 = ev["versions"][0]["id"]
    assert (
        await client.post(
            f"/ems/events/{ev['id']}/versions/{v1}/review", json={"approve": True}, headers=as_user("analyst")
        )
    ).status_code == 403  # analyst cannot approve
    r = await client.post(
        f"/ems/events/{ev['id']}/versions/{v1}/review", json={"approve": True, "comment": "ok"}, headers=as_user("lead")
    )
    assert r.json()["status"] == "active"
    assert r.json()["current_version"] == "1.0.0"
    # new optional param -> minor; second proposal blocked while pending
    r = await client.post(
        f"/ems/events/{ev['id']}/versions",
        json={
            "params": [{"name": "level", "type": "int", "required": True}, {"name": "stars", "type": "int"}],
            "changelog": "звёзды",
        },
        headers=as_user("analyst"),
    )
    assert r.json()["version"] == "1.1.0"
    assert r.json()["status"] == "pending"
    again = await client.post(f"/ems/events/{ev['id']}/versions", json={"params": []}, headers=as_user("analyst"))
    assert again.status_code == 409
    d = (
        await client.get(
            f"/ems/events/{ev['id']}/diff", params={"from": "1.0.0", "to": "1.1.0"}, headers=as_user("dev")
        )
    ).json()
    assert d["bump"] == "minor"
    assert d["changes"][0]["name"] == "stars"
    # developer reads, comments and downloads, cannot edit
    assert (
        await client.post(f"/ems/events/{ev['id']}/comments", json={"text": "в 1.9.0"}, headers=as_user("dev"))
    ).status_code == 201
    assert (
        await client.post(f"/ems/events/{ev['id']}/versions", json={"params": []}, headers=as_user("dev"))
    ).status_code == 403
    # lifecycle
    r = await client.post(f"/ems/events/{ev['id']}/status", json={"status": "archived"}, headers=as_user("lead"))
    assert r.status_code == 409  # active -> archived must go through deprecated
    r = await client.post(f"/ems/events/{ev['id']}/status", json={"status": "deprecated"}, headers=as_user("lead"))
    assert r.json()["status"] == "deprecated"
    audit = (await client.get("/admin/audit", params={"action": "event."}, headers=as_user("admin"))).json()
    assert {"event.create", "event.version_reviewed", "event.status_changed"} <= {a["action"] for a in audit["items"]}


async def test_export_schema_and_code(client: AsyncClient, world: World, as_user: H, ems: dict[str, Any]) -> None:
    ev = await _create(
        client,
        as_user("analyst"),
        ems["alpha"],
        "iap_purchase",
        [{"name": "product_id", "type": "string", "required": True}, {"name": "price_usd", "type": "float"}],
    )
    await client.post(
        f"/ems/events/{ev['id']}/versions/{ev['versions'][0]['id']}/review",
        json={"approve": True},
        headers=as_user("lead"),
    )
    r = await client.get(
        "/ems/export", params={"project_id": ems["alpha"], "format": "json_schema"}, headers=as_user("dev")
    )
    assert r.status_code == 200
    assert r.json()["iap_purchase"]["properties"]["price_usd"]["type"] == "number"
    r = await client.get("/ems/export", params={"project_id": ems["alpha"], "format": "csharp"}, headers=as_user("dev"))
    assert "public const string IapPurchase" in r.text
    r = await client.get("/ems/export/bundle", params={"project_id": ems["alpha"]}, headers=as_user("dev"))
    assert r.content[:2] == b"PK"


async def test_import_tracking_plan_csv(client: AsyncClient, world: World, as_user: H, ems: dict[str, Any]) -> None:
    csv = (
        "event_name;event_description;param_name;param_type;required;param_description;enum\n"
        "shop_open;Открыт магазин;tab;string;да;Вкладка;offers,gems\n"
        "shop_open;;source;string;нет;Откуда;\n"
        "bad event;;x;string;;;\n"
    )
    r = await client.post(
        "/ems/import",
        params={"project_id": ems["alpha"]},
        files={"file": ("plan.csv", csv.encode(), "text/csv")},
        headers=as_user("analyst"),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["created"] == ["shop_open"]
    assert len(body["errors"]) == 1
    events = (await client.get("/ems/events", params={"project_id": ems["alpha"]}, headers=as_user("analyst"))).json()
    shop = next(e for e in events if e["name"] == "shop_open")
    full = (await client.get(f"/ems/events/{shop['id']}", headers=as_user("analyst"))).json()
    tab = next(p for p in full["versions"][0]["params"] if p["name"] == "tab")
    assert tab["type"] == "enum"
    assert tab["required"] is True


async def test_discovery_and_validation_catch_ios_incident(
    client: AsyncClient, world: World, as_user: H, ems: dict[str, Any]
) -> None:
    hdr = as_user("lead")
    alpha = ems["alpha"]
    r = await client.put(f"/ems/tracking/{alpha}", json={"source_id": str(ems["source"].id)}, headers=hdr)
    assert r.status_code == 200, r.text
    found = (await client.get("/ems/discover", params={"project_id": alpha}, headers=hdr)).json()
    names = {e["name"] for e in found}
    assert {"iap_purchase", "session_start", "match_start"} <= names
    iap = next(e for e in found if e["name"] == "iap_purchase")
    assert {p["name"]: p["type"] for p in iap["params"]}["price_usd"] == "float"
    r = await client.post("/ems/discover/apply", json={"project_id": alpha, "events": found}, headers=hdr)
    assert set(r.json()["created"]) == names
    # approve everything
    for e in (await client.get("/ems/events", params={"project_id": alpha}, headers=hdr)).json():
        full = (await client.get(f"/ems/events/{e['id']}", headers=hdr)).json()
        await client.post(
            f"/ems/events/{e['id']}/versions/{full['versions'][0]['id']}/review", json={"approve": True}, headers=hdr
        )
    # a channel to be notified
    calls: list[dict[str, Any]] = []
    Notifier.transport = httpx.MockTransport(
        lambda req: calls.append({"url": str(req.url), "body": req.content}) or httpx.Response(200)
    )
    world.db.add(
        NotificationChannel(
            org_id=world.org.id,
            name="slack",
            kind="slack",
            config={},
            secrets_encrypted=encrypt_json({"webhook_url": "https://hooks.slack.test/x"}),
            min_severity="critical",
        )
    )
    await world.db.commit()
    try:
        r = await client.post(f"/ems/validate/{alpha}", headers=hdr)
    finally:
        Notifier.transport = None
    run = r.json()
    assert run["status"] == "critical", run
    alerts = (await client.get("/ems/alerts", params={"project_id": alpha}, headers=hdr)).json()
    regression = [a for a in alerts if a["kind"] == "release_regression"]
    assert regression, alerts
    assert regression[0]["event_name"] == "iap_purchase"
    assert regression[0]["details"]["platform"] == "ios"
    assert regression[0]["details"]["version"] == "1.8.0"
    assert calls
    assert b"iap_purchase" in calls[0]["body"]
    # second run deduplicates instead of creating new alerts
    await client.post(f"/ems/validate/{alpha}", headers=hdr)
    again = (await client.get("/ems/alerts", params={"project_id": alpha}, headers=hdr)).json()
    assert len(again) == len(alerts)
    # health shows up in the registry
    events = (await client.get("/ems/events", params={"project_id": alpha}, headers=hdr)).json()
    assert next(e for e in events if e["name"] == "iap_purchase")["health"] == "critical"
    gov = (await client.get("/ems/governance", params={"project_id": alpha}, headers=hdr)).json()
    assert set(gov["no_metrics"]) == names
    # acknowledge
    r = await client.post(f"/ems/alerts/{regression[0]['id']}/ack", headers=hdr)
    assert r.json()["status"] == "acknowledged"


async def test_channels_admin_only(client: AsyncClient, world: World, as_user: H, ems: dict[str, Any]) -> None:
    body = {"name": "tg", "kind": "telegram", "config": {"chat_id": "-100"}, "secrets": {"bot_token": "123:abc"}}
    assert (await client.post("/notification-channels", json=body, headers=as_user("lead"))).status_code == 403
    r = await client.post("/notification-channels", json=body, headers=as_user("admin"))
    assert r.status_code == 201
    assert r.json()["has_secrets"] is True
    assert "bot_token" not in r.json()["config"]
    rows = (await world.db.execute(select(NotificationChannel))).scalars().all()
    assert b"123:abc" not in (rows[0].secrets_encrypted or b"")
