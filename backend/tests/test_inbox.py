from __future__ import annotations

from collections.abc import Callable

from httpx import AsyncClient

from app.modules.ems.models import Alert, TrackingDraft, TrackingDraftItem
from app.modules.experiments.models import Experiment
from tests.conftest import World

H = Callable[[str], dict[str, str]]


async def test_inbox_shows_only_actionable_tasks(client: AsyncClient, world: World, as_user: H) -> None:
    await world.add_user("lead", "analytics_lead", None)
    alpha = world.projects["alpha"]
    r = await client.post(
        "/ems/events", json={"project_id": str(alpha.id), "name": "shop_open"}, headers=as_user("analyst")
    )
    assert r.status_code == 201
    draft = TrackingDraft(org_id=world.org.id, project_id=alpha.id, title="release.docx")
    world.db.add(draft)
    await world.db.flush()
    world.db.add_all(
        [
            TrackingDraftItem(draft_id=draft.id, action="create", name="a"),
            TrackingDraftItem(draft_id=draft.id, action="create", name="b", status="accepted"),
            Alert(
                org_id=world.org.id,
                project_id=alpha.id,
                kind="volume_drop",
                severity="critical",
                title="iap_purchase упал",
                fingerprint="x",
            ),
            Experiment(
                org_id=world.org.id,
                project_id=alpha.id,
                key="t",
                name="Туториал",
                metric_key="retention_d1",
                status="review",
            ),
        ]
    )
    await world.db.commit()
    params = {"project_id": str(alpha.id)}

    lead = (await client.get("/inbox", params=params, headers=as_user("lead"))).json()
    assert lead["counts"] == {
        "event_reviews": 1,
        "ai_drafts": 1,
        "alerts": 1,
        "experiment_reviews": 1,
        "experiment_decisions": 0,
    }
    assert lead["total"] == 4 and lead["tasks"][0]["kind"] == "alert"  # critical first
    assert {t["link"] for t in lead["tasks"]} >= {"/ems?event=shop_open", f"/ems?tab=aiDrafts&draft={draft.id}"}

    analyst = (await client.get("/inbox", params=params, headers=as_user("analyst"))).json()
    assert analyst["counts"]["event_reviews"] == 0 and analyst["counts"]["experiment_reviews"] == 0
    assert analyst["counts"]["ai_drafts"] == 1

    assert (await client.get("/inbox", params=params, headers=as_user("marketing"))).status_code == 404
