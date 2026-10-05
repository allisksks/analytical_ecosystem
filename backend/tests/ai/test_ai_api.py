from __future__ import annotations

import json
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select

from app.modules.ai import rag
from app.modules.ai.gateway import set_gateway
from app.modules.ai.models import AiInteraction, KbChunk
from app.modules.connectors.models import DataSource
from app.modules.connectors.service import refresh_catalog
from app.modules.kb.service import install_examples
from tests.ai.fake import FakeLLM
from tests.conftest import World

H = Callable[[str], dict[str, str]]


async def principal_of(world: World, name: str) -> Any:
    from sqlalchemy.orm import selectinload

    from app.modules.iam.models import Membership, User
    from app.modules.iam.service import build_principal

    user = await world.db.get(
        User,
        world.users[name].id,
        options=[selectinload(User.memberships).selectinload(Membership.role)],
        populate_existing=True,
    )
    assert user is not None
    return build_principal(user)


def reply(messages: list[dict[str, str]]) -> str:
    """Answers like a model: SQL for SQL prompts (a bad one first if asked), prose otherwise."""
    system = messages[0]["content"]
    last = messages[-1]["content"]
    if "SQL" in system:
        if "Запрос отклонён" in last:
            return "```sql\nSELECT COUNT(DISTINCT user_id) AS dau FROM events\n```\nИсправлено."
        if "удали" in last.lower():
            return "```sql\nDELETE FROM events\n```"
        return "```sql\nSELECT event_date, COUNT(DISTINCT user_id) AS dau FROM events GROUP BY 1 ORDER BY 1\n```\nDAU по дням."
    if "A/B" in system:
        return "Гипотеза подтвердилась: Retention D7 вырос."
    if "виджета" in system:
        return "- Пик DAU пришёлся на 3-й день."
    return "Сокращённый туториал поднял удержание [1]."


@pytest.fixture
def llm() -> Iterator[FakeLLM]:
    fake = FakeLLM(reply)
    set_gateway(fake.gateway())
    yield fake
    set_gateway(None)


@pytest.fixture
async def ai_world(world: World, demo_dir: Path) -> dict[str, Any]:
    world.projects["alpha"].data_scope = {"app_id": ["iron_shells"]}
    src = DataSource(org_id=world.org.id, name="games", type="files", config={"path": str(demo_dir)})
    world.db.add(src)
    await world.db.flush()
    await refresh_catalog(world.db, src)
    await install_examples(
        world.db, world.org.id, {"iron_shells": world.projects["alpha"], "bloom_merge": world.projects["beta"]}
    )
    await world.add_user("po", "product", ["beta"])
    await world.add_user("lead", "analytics_lead", None)
    await world.db.commit()
    return {"source": str(src.id), "alpha": str(world.projects["alpha"].id), "beta": str(world.projects["beta"].id)}


async def test_status_and_disabled(client: AsyncClient, as_user: H, ai_world: dict[str, Any]) -> None:
    st = (await client.get("/ai/status", headers=as_user("analyst"))).json()
    assert st["enabled"] is False and st["total_items"] >= 10
    r = await client.post("/ai/ask", json={"question": "Что с туториалом?"}, headers=as_user("analyst"))
    assert r.status_code == 503 and r.json()["type"] == "feature_disabled"


async def test_index_and_permission_aware_retrieval(world: World, llm: FakeLLM, ai_world: dict[str, Any]) -> None:
    from app.modules.ai.gateway import get_gateway

    gw = get_gateway()
    n = await rag.index_pending(world.db, gw)
    assert n >= 10
    assert await rag.index_pending(world.db, gw) == 0  # idempotent
    with_vec = await world.db.scalar(select(func.count()).select_from(KbChunk).where(KbChunk.embedding.is_not(None)))
    assert with_vec and with_vec > 0
    analyst = await principal_of(world, "analyst")
    hits = await rag.retrieve(world.db, analyst, "Как новый туториал повлиял на удержание?", None, gw)
    assert hits and "туториал" in hits[0].title.lower()
    po = await principal_of(world, "po")  # product role in beta only
    hits = await rag.retrieve(world.db, po, "Как новый туториал повлиял на удержание?", None, gw)
    assert all(h.project_id in (None, world.projects["beta"].id) for h in hits)


async def test_ask_stream_and_feedback(
    client: AsyncClient, world: World, as_user: H, llm: FakeLLM, ai_world: dict[str, Any]
) -> None:
    hdr = as_user("analyst")
    r = await client.post(
        "/ai/ask", json={"question": "Как туториал повлиял на удержание?", "project_id": ai_world["alpha"]}, headers=hdr
    )
    body = r.json()
    assert r.status_code == 200, r.text
    assert body["answer"] == "Сокращённый туториал поднял удержание [1]."
    assert body["sources"] and "туториал" in body["sources"][0]["title"].lower()
    prompt = llm.bodies[-1]["messages"][1]["content"]
    assert "[1]" in prompt and "Вопрос: Как туториал" in prompt

    async with client.stream(
        "POST", "/ai/ask/stream", json={"question": "Что известно про туториал?"}, headers=hdr
    ) as s:
        raw = "".join([chunk async for chunk in s.aiter_text()])
    events = [(b.split("\n")[0][7:], json.loads(b.split("\n")[1][6:])) for b in raw.strip().split("\n\n")]
    assert events[0][0] == "sources" and events[-1][0] == "done"
    assert "".join(d for e, d in events if e == "delta") == "Сокращённый туториал поднял удержание [1]."
    iid = events[-1][1]["interaction_id"]
    r = await client.post(f"/ai/interactions/{iid}/feedback", json={"rating": -1, "comment": "мало цифр"}, headers=hdr)
    assert r.json()["rating"] == -1
    assert (
        await client.post(f"/ai/interactions/{iid}/feedback", json={"rating": 1}, headers=as_user("lead"))
    ).status_code == 404
    log = (await client.get("/ai/interactions", params={"rating": -1}, headers=as_user("admin"))).json()
    assert [x["id"] for x in log] == [iid]
    # marketing has no kb:ask
    assert (
        await client.post("/ai/ask", json={"question": "туториал"}, headers=as_user("marketing"))
    ).status_code == 403


async def test_sql_generation_validates_and_repairs(
    client: AsyncClient, world: World, as_user: H, llm: FakeLLM, ai_world: dict[str, Any]
) -> None:
    hdr = as_user("analyst")
    body = {"question": "DAU по дням", "project_id": ai_world["alpha"], "source_id": ai_world["source"]}
    r = await client.post("/ai/sql", json=body, headers=hdr)
    out = r.json()
    assert r.status_code == 200, r.text
    assert out["valid"] and out["sql"].startswith("SELECT event_date") and out["explanation"] == "DAU по дням."
    assert out["examples"] and "dau_by_day_7d" in out["examples"]
    system = llm.bodies[-1]["messages"][0]["content"]
    assert "TABLE events" in system and "duckdb" in system
    # a write statement is rejected by the guard and repaired once
    r = await client.post("/ai/sql", json={**body, "question": "удали все события"}, headers=hdr)
    out = r.json()
    assert out["valid"] and out["sql"] == "SELECT COUNT(DISTINCT user_id) AS dau FROM events"
    it = await world.db.scalar(
        select(AiInteraction).where(AiInteraction.kind == "sql").order_by(AiInteraction.created_at.desc())
    )
    assert it is not None and it.prompt_tokens == 200
    # roles without ai:sql
    assert (await client.post("/ai/sql", json=body, headers=as_user("lead"))).status_code == 200
    assert (
        await client.post("/ai/sql", json=body, headers=as_user("marketing"))
    ).status_code == 404  # no access to alpha


async def test_widget_draft(client: AsyncClient, as_user: H, llm: FakeLLM, ai_world: dict[str, Any]) -> None:
    r = await client.post(
        "/ai/draft/widget",
        json={
            "project_id": ai_world["alpha"],
            "title": "DAU",
            "columns": ["day", "dau"],
            "rows": [["2026-05-01", 10], ["2026-05-02", 12]],
        },
        headers=as_user("analyst"),
    )
    assert r.json()["text"].startswith("- Пик DAU")
    assert "2026-05-02 | 12" in llm.bodies[-1]["messages"][1]["content"]


async def test_reindex_endpoint(client: AsyncClient, as_user: H, ai_world: dict[str, Any]) -> None:
    assert (await client.post("/ai/reindex", headers=as_user("analyst"))).status_code == 403
    r = await client.post("/ai/reindex", headers=as_user("lead"))
    assert r.json()["indexed"] >= 10  # without AI: text chunks for full-text retrieval


async def test_experiment_draft_sends_only_aggregates(
    client: AsyncClient, world: World, as_user: H, llm: FakeLLM, ai_world: dict[str, Any]
) -> None:
    design = {
        "project_id": ai_world["alpha"],
        "key": "tutorial_v2",
        "name": "Туториал",
        "metric_key": "retention_d1",
        "source_id": ai_world["source"],
        "segments": ["platform"],
    }
    eid = (await client.post("/experiments", json=design, headers=as_user("lead"))).json()["id"]
    r = await client.post(f"/ai/draft/experiment/{eid}", headers=as_user("lead"))
    assert r.status_code == 404  # not calculated yet
    await client.post(f"/experiments/{eid}/transition", json={"to": "review"}, headers=as_user("lead"))
    await client.post(f"/experiments/{eid}/transition", json={"to": "running"}, headers=as_user("lead"))
    r = await client.post(f"/ai/draft/experiment/{eid}", headers=as_user("lead"))
    assert r.json()["text"].startswith("Гипотеза подтвердилась")
    payload = llm.bodies[-1]["messages"][1]["content"]
    assert '"prob_better"' in payload and "user_id" not in payload
    assert (await client.post(f"/ai/draft/experiment/{eid}", headers=as_user("marketing"))).status_code == 404
