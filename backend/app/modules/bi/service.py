"""Dashboards: access rules, role templates from the domain pack, widget data through the semantic layer."""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFoundError, PermissionDenied, ValidationFailed
from app.modules.bi.models import Dashboard, DashboardGrant, Widget
from app.modules.connectors.service import get_source
from app.modules.iam.models import Project
from app.modules.iam.permissions import P
from app.modules.iam.policy import Principal
from app.modules.query import service as query_service
from app.modules.semantic import service as semantic
from app.modules.semantic.compiler import Filter

VIZ = {"line", "bar", "area", "heatmap", "table", "kpi", "pie"}
PLACEHOLDER = re.compile(r"\{\{\s*(date_from|date_to)\s*\}\}")


def templates(pack: str = "gaming") -> list[dict[str, Any]]:
    path = semantic.PACKS_DIR / pack / "dashboards.yaml"
    if not Path(path).exists():
        return []
    return list(yaml.safe_load(path.read_text(encoding="utf-8")).get("dashboards", []))


async def _granted(db: AsyncSession, principal: Principal, dash: Dashboard) -> bool:
    grant = (
        await db.execute(
            select(DashboardGrant).where(DashboardGrant.dashboard_id == dash.id, DashboardGrant.user_id == principal.id)
        )
    ).scalar_one_or_none()
    return grant is not None and (grant.expires_at is None or grant.expires_at > datetime.now(UTC))


async def can_view(db: AsyncSession, principal: Principal, dash: Dashboard) -> bool:
    if dash.org_id != principal.org_id:
        return False
    if dash.project_id is None:
        return principal.can(P.PORTFOLIO_VIEW)
    visible = principal.visible_project_ids()
    if visible is not None and dash.project_id not in visible:
        return False
    if principal.can(P.DASHBOARDS_VIEW, dash.project_id):
        return True
    return principal.can(P.DASHBOARDS_VIEW_SHARED, dash.project_id) and await _granted(db, principal, dash)


def can_edit(principal: Principal, dash: Dashboard) -> bool:
    if dash.project_id is None:
        return principal.can(P.DASHBOARDS_EDIT) and principal.can(P.PORTFOLIO_VIEW)
    if principal.can(P.DASHBOARDS_EDIT, dash.project_id):
        return True
    return principal.can(P.DASHBOARDS_EDIT_OWN, dash.project_id) and dash.owner_id == principal.id


def can_create(principal: Principal, project_id: uuid.UUID | None) -> bool:
    if project_id is None:
        return principal.can(P.DASHBOARDS_EDIT) and principal.can(P.PORTFOLIO_VIEW)
    return principal.can(P.DASHBOARDS_EDIT, project_id) or principal.can(P.DASHBOARDS_EDIT_OWN, project_id)


async def get_dashboard(
    db: AsyncSession, principal: Principal, dashboard_id: uuid.UUID, *, edit: bool = False
) -> Dashboard:
    dash = await db.get(Dashboard, dashboard_id)
    if dash is None or not await can_view(db, principal, dash):
        raise NotFoundError("Дашборд не найден")
    if edit and not can_edit(principal, dash):
        raise PermissionDenied("Нет прав на редактирование дашборда", details={"permission": P.DASHBOARDS_EDIT})
    return dash


async def create_from_template(
    db: AsyncSession,
    org_id: uuid.UUID,
    project: Project | None,
    tpl: dict[str, Any],
    owner_id: uuid.UUID | None,
    position: int = 0,
) -> Dashboard:
    dash = Dashboard(
        org_id=org_id,
        project_id=project.id if project else None,
        title=tpl["title"],
        role=tpl.get("role", ""),
        template_key=tpl["key"],
        owner_id=owner_id,
        position=position,
        filters={"period_days": 30},
        widgets=[],
    )
    for i, w in enumerate(tpl.get("widgets", [])):
        dash.widgets.append(
            Widget(
                title=w["title"],
                viz=w["viz"],
                mode="semantic",
                spec=w.get("spec", {}),
                layout=w.get("layout", {}),
                settings=w.get("settings", {}),
                position=i,
                observation=w.get("observation", ""),
                observation_author="starter-kit" if w.get("observation") else "",
            )
        )
    db.add(dash)
    await db.flush()
    return dash


# ------------------------------------------------------------------ widget data
@dataclass
class GlobalFilters:
    date_from: date | None = None
    date_to: date | None = None
    filters: list[Filter] = field(default_factory=list)


def effective_range(dash: Dashboard, g: GlobalFilters) -> tuple[date, date]:
    if g.date_from and g.date_to:
        return g.date_from, g.date_to
    days = int((dash.filters or {}).get("period_days", 30))
    today = datetime.now(UTC).date()
    return g.date_from or today - timedelta(days=days - 1), g.date_to or today


@dataclass
class WidgetData:
    columns: list[dict[str, str]]
    rows: list[list[Any]]
    sql: list[str]
    cached: bool


async def widget_data(
    db: AsyncSession,
    principal: Principal,
    project: Project | None,
    widget_mode: str,
    spec: dict[str, Any],
    date_from: date,
    date_to: date,
    extra_filters: list[Filter],
) -> WidgetData:
    if widget_mode == "sql":
        source_id = spec.get("source_id")
        sql = str(spec.get("sql", ""))
        if not source_id or not sql:
            raise ValidationFailed("Для SQL-блока нужны источник и запрос")
        source = await get_source(db, principal, uuid.UUID(str(source_id)))
        values = {"date_from": date_from.isoformat(), "date_to": date_to.isoformat()}
        # dates are formatted by us (ISO), never taken verbatim from the client
        sql = PLACEHOLDER.sub(lambda m: f"'{values[m.group(1)]}'", sql)
        out = await query_service.execute(
            db, principal, source, project, sql, origin="widget", limit=int(spec.get("limit", 5000))
        )
        cols = [
            {"key": c["name"], "name": c["name"], "role": "metric" if _is_num(c["type"]) else "dimension", "format": ""}
            for c in out.columns
        ]
        return WidgetData(cols, out.rows, [out.executed_sql], out.cached)
    filters = [Filter(f["dimension"], f.get("op", "in"), tuple(f.get("values", []))) for f in spec.get("filters", [])]
    req = semantic.SemanticRequest(
        metrics=list(spec.get("metrics", [])),
        dimensions=list(spec.get("dimensions", [])),
        grain=spec.get("grain", "none"),
        date_from=date_from,
        date_to=date_to,
        filters=[*filters, *extra_filters],
        cohorts=[
            semantic.Cohort(
                c["label"],
                [Filter(f["dimension"], f.get("op", "in"), tuple(f["values"])) for f in c.get("filters", [])],
            )
            for c in spec.get("cohorts", [])
        ],
    )
    res = await semantic.run(db, principal, project, req, origin="widget")
    return WidgetData(res.columns, res.rows, res.sql, res.cached)


def _is_num(t: str) -> bool:
    return bool(re.search(r"int|float|double|decimal|numeric|real|hugeint", t, re.I))
