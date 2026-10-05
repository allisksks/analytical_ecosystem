from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
from httpx import AsyncClient

from app.modules.semantic.compiler import DimensionDef, MetricDef, SemanticSpec, compile_spec
from app.modules.semantic.service import install_pack
from tests.conftest import World

H = Callable[[str], dict[str, str]]


@pytest.fixture
async def metrics(world: World, demo_source: Any) -> None:
    await install_pack(world.db, world.org.id, "gaming")
    await world.db.commit()


def test_window_metrics_are_partitioned_by_other_dimensions() -> None:
    m = MetricDef(
        "curve",
        "mart_retention",
        "install_date",
        "COUNT(*) * 1.0 / MAX(COUNT(*)) OVER ()",
        default_dimensions=("day_n",),
    )
    sql = compile_spec(
        SemanticSpec([m], [DimensionDef("day_n", "day_n"), DimensionDef("platform", "platform")]), "duckdb"
    )[0].sql
    assert 'OVER (PARTITION BY "platform")' in sql


async def test_query_respects_project_scope(client: AsyncClient, world: World, as_user: H, metrics: None) -> None:
    body = {
        "project_id": str(world.projects["alpha"].id),
        "metrics": ["dau", "revenue", "retention_d1"],
        "dimensions": ["app_id"],
        "grain": "none",
    }
    r = await client.post("/semantic/query", json=body, headers=as_user("analyst"))
    assert r.status_code == 200, r.text
    data = r.json()
    assert [c["key"] for c in data["columns"]] == ["app_id", "dau", "revenue", "retention_d1"]
    assert [row[0] for row in data["rows"]] == ["iron_shells"]
    assert 0 < data["rows"][0][3] < 1
    assert data["columns"][3]["format"] == "percent"


async def test_cohort_comparison_of_two_releases(client: AsyncClient, world: World, as_user: H, metrics: None) -> None:
    await world.add_user("po", "product", ["alpha"])
    await world.db.commit()
    body = {
        "project_id": str(world.projects["alpha"].id),
        "metrics": ["retention_curve"],
        "dimensions": ["day_n"],
        "cohorts": [
            {"label": "1.6.0", "filters": [{"dimension": "app_version", "values": ["1.6.0"]}]},
            {"label": "1.7.0", "filters": [{"dimension": "app_version", "values": ["1.7.0"]}]},
        ],
    }
    r = await client.post("/semantic/query", json=body, headers=as_user("po"))
    assert r.status_code == 200, r.text
    rows = r.json()["rows"]
    day0 = [row for row in rows if row[1] == 0]
    assert {row[0] for row in day0} == {"1.6.0", "1.7.0"}
    assert all(row[2] == 1.0 for row in day0)


async def test_portfolio_requires_executive(client: AsyncClient, world: World, as_user: H, metrics: None) -> None:
    body = {"metrics": ["portfolio_revenue"], "dimensions": ["app_id"]}
    assert (await client.post("/semantic/query", json=body, headers=as_user("analyst"))).status_code == 403
    r = await client.post("/semantic/query", json=body, headers=as_user("ceo"))
    assert r.status_code == 200, r.text
    assert len(r.json()["rows"]) == 3  # whole portfolio, no project scope


async def test_marketing_cannot_query_foreign_project(
    client: AsyncClient, world: World, as_user: H, metrics: None
) -> None:
    body = {"project_id": str(world.projects["alpha"].id), "metrics": ["installs"]}
    assert (await client.post("/semantic/query", json=body, headers=as_user("marketing"))).status_code == 404


async def test_metric_versioning_and_validation(client: AsyncClient, world: World, as_user: H, metrics: None) -> None:
    listed = (await client.get("/semantic/metrics", headers=as_user("analyst"))).json()
    dau = next(m for m in listed if m["key"] == "dau")
    assert (
        await client.patch(f"/semantic/metrics/{dau['id']}", json={"name": "x"}, headers=as_user("analyst"))
    ).status_code == 403
    await world.add_user("lead", "analytics_lead", None)
    await world.db.commit()
    r = await client.patch(f"/semantic/metrics/{dau['id']}", json={"expression": "dau"}, headers=as_user("lead"))
    assert r.status_code == 422  # no aggregate
    r = await client.patch(
        f"/semantic/metrics/{dau['id']}", json={"description": "Среднее DAU"}, headers=as_user("lead")
    )
    assert r.json()["version"] == 2
    versions = (await client.get(f"/semantic/metrics/{dau['id']}/versions", headers=as_user("lead"))).json()
    assert [v["version"] for v in versions] == [2, 1]
    assert versions[0]["author"] == "lead@test.io"


async def test_dimension_not_in_table_is_reported(client: AsyncClient, world: World, as_user: H, metrics: None) -> None:
    body = {"project_id": str(world.projects["alpha"].id), "metrics": ["installs"], "dimensions": ["platform"]}
    r = await client.post("/semantic/query", json=body, headers=as_user("analyst"))
    assert r.status_code == 422
    assert "platform" in r.json()["title"]


async def test_dimension_values_respect_scope(client: AsyncClient, world: World, as_user: H, metrics: None) -> None:
    r = await client.get(
        "/semantic/dimensions/app_id/values",
        params={"project_id": str(world.projects["alpha"].id)},
        headers=as_user("analyst"),
    )
    assert r.json() == ["iron_shells"]
    r = await client.get(
        "/semantic/dimensions/platform/values",
        params={"project_id": str(world.projects["alpha"].id)},
        headers=as_user("analyst"),
    )
    assert r.json() == ["android", "ios"]
