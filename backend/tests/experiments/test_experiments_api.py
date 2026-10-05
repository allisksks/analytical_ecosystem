from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import duckdb
import pytest
from httpx import AsyncClient

from app.modules.connectors.models import DataSource
from app.modules.connectors.service import refresh_catalog
from tests.conftest import World

H = Callable[[str], dict[str, str]]


@pytest.fixture
async def ab(world: World, demo_dir_full: Path) -> dict[str, Any]:
    world.projects["alpha"].data_scope = {"app_id": ["iron_shells"]}
    world.projects["beta"].data_scope = {"app_id": ["drift_kings"]}
    src = DataSource(org_id=world.org.id, name="games", type="files", config={"path": str(demo_dir_full)})
    world.db.add(src)
    await world.db.flush()
    await refresh_catalog(world.db, src)
    await world.add_user("lead", "analytics_lead", None)
    await world.add_user("dev", "developer", ["alpha"])
    await world.add_user("po", "product", ["alpha"])
    await world.db.commit()
    return {
        "source": str(src.id),
        "alpha": str(world.projects["alpha"].id),
        "beta": str(world.projects["beta"].id),
        "dir": demo_dir_full,
    }


def _design(ab: dict[str, Any], **kw: Any) -> dict[str, Any]:
    return {
        "project_id": ab["alpha"],
        "key": "tutorial_v2",
        "name": "Новый туториал",
        "metric_key": "retention_d1",
        "secondary_metrics": ["arpu_d7"],
        "segments": ["platform"],
        "source_id": ab["source"],
        "variants": [{"key": "A", "weight": 1}, {"key": "B", "weight": 1}],
        "planned_users": 100,
        **kw,
    }


def _expected_d1(demo: Path) -> dict[str, tuple[int, int]]:
    """Direct computation of Retention D1 per variant with DuckDB (independent of the platform's SQL)."""
    c = duckdb.connect()
    rows = c.sql(f"""
        WITH a AS (SELECT * FROM '{demo}/ab_assignments.parquet' WHERE app_id = 'iron_shells' AND experiment_key = 'tutorial_v2'
                   AND CAST(assigned_at AS DATE) <= (SELECT MAX(activity_date) FROM '{demo}/mart_retention.parquet'
                                                     WHERE app_id = 'iron_shells') - 1),
             r AS (SELECT DISTINCT user_id FROM '{demo}/mart_retention.parquet' WHERE app_id = 'iron_shells' AND day_n = 1)
        SELECT variant, COUNT(*), COUNT(r.user_id) FROM a LEFT JOIN r USING (user_id) GROUP BY 1""").fetchall()
    return {v: (int(n), int(k)) for v, n, k in rows}


async def test_lifecycle_results_decision_and_kb(client: AsyncClient, as_user: H, ab: dict[str, Any]) -> None:
    r = await client.post("/experiments", json=_design(ab), headers=as_user("analyst"))
    assert r.status_code == 201, r.text
    exp = r.json()
    assert exp["status"] == "draft"
    assert [v["weight"] for v in exp["variants"]] == [0.5, 0.5]  # normalised
    eid = exp["id"]

    assert (
        await client.post(f"/experiments/{eid}/transition", json={"to": "running"}, headers=as_user("analyst"))
    ).status_code == 409
    r = await client.post(f"/experiments/{eid}/transition", json={"to": "review"}, headers=as_user("analyst"))
    assert r.json()["status"] == "review"
    r = await client.post(f"/experiments/{eid}/transition", json={"to": "running"}, headers=as_user("analyst"))
    assert r.status_code == 403  # only the gatekeeper launches
    r = await client.post(f"/experiments/{eid}/transition", json={"to": "running"}, headers=as_user("lead"))
    assert r.status_code == 200, r.text
    exp = r.json()
    assert exp["status"] == "running" and exp["approved_by"] == "lead@test.io"

    # results were calculated on launch and match an independent computation
    res = exp["result"]
    expected = _expected_d1(ab["dir"])
    got = {v["key"]: v for v in res["primary"]["variants"]}
    for k, (n, retained) in expected.items():
        assert got[k]["n"] == n
        assert got[k]["mean"] == pytest.approx(retained / n)
    assert res["srm"]["mismatch"] is False
    assert 0 <= res["primary"]["comparisons"][0]["prob_better"] <= 1
    assert res["primary"]["comparisons"][0]["frequentist"]["method"] == "two-proportion z-test"
    assert res["secondary"][0]["metric"] == "arpu_d7"
    assert res["secondary"][0]["comparisons"][0]["method"] == "bayesian-bootstrap"
    assert {s["value"] for s in res["segments"]} == {"ios", "android"}
    assert res["recommendation"] in ("ship", "keep_control", "inconclusive", "continue")
    assert exp["prob_best"] == res["primary"]["comparisons"][0]["prob_better"]

    # design is frozen while running
    r = await client.patch(f"/experiments/{eid}", json={"metric_key": "retention_d7"}, headers=as_user("analyst"))
    assert r.status_code == 409
    r = await client.patch(f"/experiments/{eid}", json={"description": "в процессе"}, headers=as_user("analyst"))
    assert r.json()["description"] == "в процессе"

    r = await client.post(f"/experiments/{eid}/recalculate", headers=as_user("analyst"))
    assert len(r.json()["history"]) == 2

    # executives only see finished experiments
    assert (await client.get(f"/experiments/{eid}", headers=as_user("ceo"))).status_code == 404
    lst = await client.get("/experiments", params={"project_id": ab["alpha"]}, headers=as_user("ceo"))
    assert lst.json() == []

    r = await client.post(f"/experiments/{eid}/transition", json={"to": "completed"}, headers=as_user("analyst"))
    assert r.json()["ended_at"]
    body = {"decision": "ship", "conclusion": "Раскатываем B на всех"}
    assert (await client.post(f"/experiments/{eid}/decision", json=body, headers=as_user("analyst"))).status_code == 403
    r = await client.post(f"/experiments/{eid}/decision", json=body, headers=as_user("lead"))
    assert r.json()["decision"] == "ship"
    assert (await client.get(f"/experiments/{eid}", headers=as_user("ceo"))).status_code == 200

    r = await client.post(f"/experiments/{eid}/kb", headers=as_user("analyst"))
    assert r.status_code == 200, r.text
    kb_id = r.json()["kb_item_id"]
    item = (await client.get(f"/kb/{kb_id}", headers=as_user("analyst"))).json()
    assert item["type"] == "experiment" and item["decision"] == "accepted"
    assert "| Retention D1 | B |" in item["body"]
    assert {"kind": "experiment", "ref": eid, "title": "tutorial_v2"} in item["links"]
    assert (await client.post(f"/experiments/{eid}/kb", headers=as_user("analyst"))).status_code == 409

    md = await client.get(f"/experiments/{eid}/report.md", headers=as_user("analyst"))
    assert md.headers["content-type"].startswith("text/markdown") and "## Вывод и решение" in md.text


async def test_design_validation(client: AsyncClient, as_user: H, ab: dict[str, Any]) -> None:
    hdr = as_user("analyst")
    assert (await client.post("/experiments", json=_design(ab, metric_key="dau"), headers=hdr)).status_code == 422
    assert (await client.post("/experiments", json=_design(ab, segments=["user_id"]), headers=hdr)).status_code == 422
    one = _design(ab, variants=[{"key": "A"}])
    assert (await client.post("/experiments", json=one, headers=hdr)).status_code == 422
    assert (await client.post("/experiments", json=_design(ab), headers=hdr)).status_code == 201
    assert (await client.post("/experiments", json=_design(ab), headers=hdr)).status_code == 409
    # marketing has no rights in alpha; product may propose; developers only read
    assert (
        await client.post("/experiments", json=_design(ab, key="x1"), headers=as_user("marketing"))
    ).status_code == 404
    assert (await client.post("/experiments", json=_design(ab, key="x2"), headers=as_user("dev"))).status_code == 403
    r = await client.post("/experiments", json=_design(ab, key="x3"), headers=as_user("po"))
    assert r.status_code == 201
    # the proposer may tweak own draft, not someone else's
    eid = r.json()["id"]
    assert (await client.patch(f"/experiments/{eid}", json={"mde": 0.1}, headers=as_user("po"))).status_code == 200


async def test_row_rules_apply_to_results(client: AsyncClient, as_user: H, ab: dict[str, Any]) -> None:
    """The same experiment key in another project only sees that project's rows (no assignments there)."""
    r = await client.post("/experiments", json=_design(ab, project_id=ab["beta"]), headers=as_user("admin"))
    assert r.status_code == 403  # admin has no experiments:propose
    r = await client.post("/experiments", json=_design(ab, project_id=ab["beta"]), headers=as_user("lead"))
    eid = r.json()["id"]
    await client.post(f"/experiments/{eid}/transition", json={"to": "review"}, headers=as_user("lead"))
    r = await client.post(f"/experiments/{eid}/transition", json={"to": "running"}, headers=as_user("lead"))
    res = r.json()["result"]
    assert res["assigned"] == {"A": 0, "B": 0}
    assert res["recommendation"] == "collecting"


async def test_internal_splitter_and_sdk_config(client: AsyncClient, as_user: H, ab: dict[str, Any]) -> None:
    r = await client.post(
        "/experiments", json=_design(ab, key="offer", splitter="internal", traffic_share=0.5), headers=as_user("lead")
    )
    eid = r.json()["id"]
    body = {"project_id": ab["alpha"], "experiment_key": "offer", "user_id": "u42"}
    assert (await client.post("/experiments/assign", json=body, headers=as_user("dev"))).json()["variant"] is None
    await client.post(f"/experiments/{eid}/transition", json={"to": "review"}, headers=as_user("lead"))
    await client.post(f"/experiments/{eid}/transition", json={"to": "running"}, headers=as_user("lead"))
    variants = {
        (await client.post("/experiments/assign", json={**body, "user_id": f"u{i}"}, headers=as_user("dev"))).json()[
            "variant"
        ]
        for i in range(40)
    }
    assert variants == {"A", "B", None}
    cfg = (
        await client.get("/experiments/sdk-config", params={"project_id": ab["alpha"]}, headers=as_user("dev"))
    ).json()
    assert cfg == [
        {
            "key": "offer",
            "salt": "v1",
            "traffic_share": 0.5,
            "variants": [{"key": "A", "weight": 0.5}, {"key": "B", "weight": 0.5}],
        }
    ]


async def test_power_baseline_and_templates(client: AsyncClient, as_user: H, ab: dict[str, Any]) -> None:
    hdr = as_user("analyst")
    tpl = (await client.get("/experiments/metrics", headers=hdr)).json()
    assert {t["key"] for t in tpl} >= {"retention_d1", "arpu_d7"}
    r = await client.get(
        "/experiments/baseline",
        params={"project_id": ab["alpha"], "source_id": ab["source"], "metric_key": "retention_d1"},
        headers=hdr,
    )
    base = r.json()
    assert r.status_code == 200, r.text
    assert 0.1 < base["baseline"] < 0.7 and base["daily_users"] > 0
    r = await client.post(
        "/experiments/power",
        json={"metric_type": "binary", "baseline": base["baseline"], "mde": 0.05, "daily_users": base["daily_users"]},
        headers=hdr,
    )
    assert r.json()["per_group"] > 1000 and r.json()["days"] > 0
    r = await client.post(
        "/experiments/power", json={"metric_type": "continuous", "baseline": 1, "mde": 0.05}, headers=hdr
    )
    assert r.status_code == 422  # needs sd


async def test_worker_recalculates_running(client: AsyncClient, world: World, as_user: H, ab: dict[str, Any]) -> None:
    from app.modules.experiments.service import recalculate_all

    r = await client.post("/experiments", json=_design(ab), headers=as_user("lead"))
    eid = r.json()["id"]
    await client.post(f"/experiments/{eid}/transition", json={"to": "review"}, headers=as_user("lead"))
    await client.post(f"/experiments/{eid}/transition", json={"to": "running"}, headers=as_user("lead"))
    assert await recalculate_all(world.db) == 1
    r = await client.get(f"/experiments/{eid}", headers=as_user("analyst"))
    assert len(r.json()["history"]) == 2
