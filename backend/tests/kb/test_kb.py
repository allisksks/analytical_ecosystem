from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
from httpx import AsyncClient

from app.modules.kb.service import install_examples
from tests.conftest import World

H = Callable[[str], dict[str, str]]


@pytest.fixture
async def kb(world: World) -> None:
    projects = {"iron_shells": world.projects["alpha"], "drift_kings": world.projects["beta"],
                "bloom_merge": world.projects["beta"]}  # fmt: skip
    await install_examples(world.db, world.org.id, projects)
    await world.add_user("lead", "analytics_lead", None)
    await world.db.commit()


async def test_full_text_search_in_russian_with_facets(client: AsyncClient, world: World, as_user: H, kb: None) -> None:
    r = await client.get(
        "/kb", params={"q": "что мы уже тестировали с ценой стартового оффера"}, headers=as_user("lead")
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["items"][0]["title"].startswith("Iron Shells · Стартовый набор")
    assert body["facets"]["types"]["experiment"] >= 1
    r = await client.get("/kb", params={"type": "incident_report"}, headers=as_user("lead"))
    assert [i["type"] for i in r.json()["items"]] == ["incident_report"]
    r = await client.get("/kb", params={"tag": "ab"}, headers=as_user("lead"))
    assert all("ab" in i["tags"] for i in r.json()["items"])
    assert {t["tag"] for t in r.json()["facets"]["tags"]} >= {"ab", "retention"}


async def test_project_scoping(client: AsyncClient, world: World, as_user: H, kb: None) -> None:
    analyst = (await client.get("/kb", params={"limit": 100}, headers=as_user("analyst"))).json()
    titles = [i["title"] for i in analyst["items"]]
    assert any("Iron Shells" in t for t in titles)  # own project
    assert not any("Drift Kings" in t for t in titles)  # other project
    assert any("LiveOps" in t for t in titles)  # organisation-wide playbook
    marketing = (await client.get("/kb", params={"limit": 100}, headers=as_user("marketing"))).json()
    alpha = str(world.projects["alpha"].id)
    assert not any(i["project_id"] == alpha for i in marketing["items"])


async def test_create_edit_versions_comments(client: AsyncClient, world: World, as_user: H, kb: None) -> None:
    alpha = str(world.projects["alpha"].id)
    r = await client.post(
        "/kb",
        json={
            "project_id": alpha,
            "type": "research",
            "title": "Анализ воронки магазина",
            "summary": "Черновик",
            "tags": ["#Shop", "funnel"],
        },
        headers=as_user("analyst"),
    )
    assert r.status_code == 201, r.text
    item = r.json()
    assert item["tags"] == ["funnel", "shop"]
    assert item["can_edit"] is True
    iid = item["id"]
    r = await client.patch(f"/kb/{iid}", json={"body": "## Находки\n1. Витрина режет 30%"}, headers=as_user("analyst"))
    assert r.json()["version"] == 2
    r = await client.patch(f"/kb/{iid}", json={"tags": ["shop"]}, headers=as_user("analyst"))
    assert r.json()["version"] == 2  # metadata changes do not create versions
    versions = (await client.get(f"/kb/{iid}/versions", headers=as_user("analyst"))).json()
    assert [v["version"] for v in versions] == [2, 1]
    # product reads but cannot edit; can comment
    await world.add_user("po", "product", ["alpha"])
    await world.db.commit()
    assert (await client.patch(f"/kb/{iid}", json={"title": "x"}, headers=as_user("po"))).status_code == 403
    r = await client.post(f"/kb/{iid}/comments", json={"text": "А на Android?"}, headers=as_user("po"))
    assert r.status_code == 201
    assert (await client.get(f"/kb/{iid}", headers=as_user("analyst"))).json()["comments"][0]["text"] == "А на Android?"
    # moderator can edit someone else's record
    assert (await client.patch(f"/kb/{iid}", json={"status": "archived"}, headers=as_user("lead"))).status_code == 200


async def test_marketing_cannot_write(client: AsyncClient, world: World, as_user: H, kb: None) -> None:
    beta = str(world.projects["beta"].id)
    r = await client.post("/kb", json={"project_id": beta, "type": "case", "title": "x"}, headers=as_user("marketing"))
    assert r.status_code == 403


async def test_attachments(
    client: AsyncClient, world: World, as_user: H, kb: None, tmp_path: Any, monkeypatch: Any
) -> None:
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "storage_dir", str(tmp_path))
    alpha = str(world.projects["alpha"].id)
    iid = (
        await client.post("/kb", json={"project_id": alpha, "type": "case", "title": "c"}, headers=as_user("analyst"))
    ).json()["id"]
    r = await client.post(
        f"/kb/{iid}/attachments", files={"file": ("chart.png", b"\x89PNG...", "image/png")}, headers=as_user("analyst")
    )
    assert r.status_code == 201, r.text
    att = r.json()
    r = await client.get(f"/kb/{iid}/attachments/{att['id']}", headers=as_user("analyst"))
    assert r.content == b"\x89PNG..."
    bad = await client.post(
        f"/kb/{iid}/attachments", files={"file": ("x.sh", b"rm -rf", "application/x-sh")}, headers=as_user("analyst")
    )
    assert bad.status_code == 422
