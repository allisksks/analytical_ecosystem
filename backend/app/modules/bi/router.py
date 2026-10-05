"""Dashboards API: CRUD, role templates, widget data with global filters, sharing."""

from __future__ import annotations

import secrets
import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Response
from sqlalchemy import func, select

from app.core.errors import NotFoundError, PermissionDenied, ValidationFailed
from app.modules.audit.service import record
from app.modules.bi import service
from app.modules.bi.models import Dashboard, DashboardGrant, Widget
from app.modules.bi.schemas import (
    DashboardIn,
    DashboardOut,
    DashboardPatch,
    DashboardSummary,
    DataIn,
    DataOut,
    FromTemplateIn,
    GrantIn,
    LayoutItem,
    PreviewIn,
    ShareIn,
    ShareOut,
    TemplateOut,
    WidgetIn,
    WidgetOut,
    WidgetPatch,
)
from app.modules.iam.deps import DB, CurrentPrincipal
from app.modules.iam.models import Project, User
from app.modules.iam.policy import Principal
from app.modules.iam.service import build_principal
from app.modules.query.service import load_project
from app.modules.semantic.compiler import Filter

router = APIRouter(tags=["bi"])


def summary(d: Dashboard, principal: Principal | None) -> DashboardSummary:
    out = DashboardSummary.model_validate(d)
    out.can_edit = bool(principal and service.can_edit(principal, d))
    return out


def full(d: Dashboard, principal: Principal | None) -> DashboardOut:
    return DashboardOut(
        **summary(d, principal).model_dump(),
        filters=d.filters or {},
        widgets=[WidgetOut.model_validate(w) for w in d.widgets],
        share_expires_at=d.share_expires_at,
        shared=bool(d.share_token and d.share_expires_at and d.share_expires_at > datetime.now(UTC)),
    )


@router.get("/dashboards/templates", response_model=list[TemplateOut])
async def list_templates(_: CurrentPrincipal) -> list[TemplateOut]:
    return [
        TemplateOut(
            key=t["key"],
            title=t["title"],
            role=t.get("role", ""),
            scope=t.get("scope", "project"),
            widgets=len(t.get("widgets", [])),
        )
        for t in service.templates()
    ]


@router.get("/dashboards", response_model=list[DashboardSummary])
async def list_dashboards(
    principal: CurrentPrincipal, db: DB, project_id: uuid.UUID | None = None, portfolio: bool = False
) -> list[DashboardSummary]:
    q = select(Dashboard).where(Dashboard.org_id == principal.org_id)
    q = q.where(Dashboard.project_id.is_(None)) if portfolio else q.where(Dashboard.project_id == project_id)
    out = []
    for d in (await db.execute(q.order_by(Dashboard.position, Dashboard.title))).scalars():
        if await service.can_view(db, principal, d):
            out.append(summary(d, principal))
    return out


@router.post("/dashboards", response_model=DashboardOut, status_code=201)
async def create_dashboard(body: DashboardIn, principal: CurrentPrincipal, db: DB) -> DashboardOut:
    project = await load_project(db, principal, body.project_id)
    if not service.can_create(principal, body.project_id):
        raise PermissionDenied("Нет прав на создание дашбордов")
    pos = await db.scalar(
        select(func.coalesce(func.max(Dashboard.position), 0) + 1).where(
            Dashboard.org_id == principal.org_id, Dashboard.project_id == body.project_id
        )
    )
    d = Dashboard(
        org_id=principal.org_id,
        project_id=project.id if project else None,
        title=body.title,
        description=body.description,
        filters=body.filters,
        owner_id=principal.id,
        position=pos or 0,
        widgets=[],
    )
    db.add(d)
    await db.flush()
    await record(
        db,
        "dashboard.create",
        principal=principal,
        resource_type="dashboard",
        resource_id=d.id,
        project_id=d.project_id,
    )
    await db.commit()
    await db.refresh(d)
    return full(d, principal)


@router.post("/dashboards/from-template", response_model=DashboardOut, status_code=201)
async def from_template(body: FromTemplateIn, principal: CurrentPrincipal, db: DB) -> DashboardOut:
    tpl = next((t for t in service.templates() if t["key"] == body.template_key), None)
    if tpl is None:
        raise NotFoundError("Шаблон не найден")
    project = None if tpl.get("scope") == "portfolio" else await load_project(db, principal, body.project_id)
    if tpl.get("scope") != "portfolio" and project is None:
        raise ValidationFailed("Выберите проект")
    if not service.can_create(principal, project.id if project else None):
        raise PermissionDenied("Нет прав на создание дашбордов")
    d = await service.create_from_template(db, principal.org_id, project, tpl, principal.id)
    await db.commit()
    await db.refresh(d)
    return full(d, principal)


@router.get("/dashboards/{dashboard_id}", response_model=DashboardOut)
async def read_dashboard(dashboard_id: uuid.UUID, principal: CurrentPrincipal, db: DB) -> DashboardOut:
    return full(await service.get_dashboard(db, principal, dashboard_id), principal)


@router.patch("/dashboards/{dashboard_id}", response_model=DashboardOut)
async def update_dashboard(
    dashboard_id: uuid.UUID, body: DashboardPatch, principal: CurrentPrincipal, db: DB
) -> DashboardOut:
    d = await service.get_dashboard(db, principal, dashboard_id, edit=True)
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(d, k, v)
    await db.commit()
    await db.refresh(d)
    return full(d, principal)


@router.delete("/dashboards/{dashboard_id}", status_code=204)
async def delete_dashboard(dashboard_id: uuid.UUID, principal: CurrentPrincipal, db: DB) -> Response:
    d = await service.get_dashboard(db, principal, dashboard_id, edit=True)
    await db.delete(d)
    await record(db, "dashboard.delete", principal=principal, resource_type="dashboard", resource_id=dashboard_id)
    await db.commit()
    return Response(status_code=204)


# ------------------------------------------------------------------ widgets
@router.post("/dashboards/{dashboard_id}/widgets", response_model=WidgetOut, status_code=201)
async def add_widget(dashboard_id: uuid.UUID, body: WidgetIn, principal: CurrentPrincipal, db: DB) -> Widget:
    d = await service.get_dashboard(db, principal, dashboard_id, edit=True)
    _check_widget_mode(principal, d, body.mode)
    w = Widget(
        dashboard_id=d.id,
        position=len(d.widgets),
        observation_author=principal.label if body.observation else "",
        **body.model_dump(),
    )
    db.add(w)
    await db.commit()
    await db.refresh(w)
    return w


def _check_widget_mode(principal: Principal, d: Dashboard, mode: str | None) -> None:
    from app.modules.iam.permissions import P

    if mode == "sql" and not (principal.can(P.SQL_RUN, d.project_id) or principal.can(P.SQL_RUN_ALL)):
        raise PermissionDenied("SQL-блоки доступны ролям с правом на SQL", details={"permission": P.SQL_RUN})


async def _widget(db: DB, principal: Principal, widget_id: uuid.UUID, edit: bool) -> tuple[Widget, Dashboard]:
    w = await db.get(Widget, widget_id)
    if w is None:
        raise NotFoundError("Блок не найден")
    d = await service.get_dashboard(db, principal, w.dashboard_id, edit=edit)
    return w, d


@router.patch("/widgets/{widget_id}", response_model=WidgetOut)
async def update_widget(widget_id: uuid.UUID, body: WidgetPatch, principal: CurrentPrincipal, db: DB) -> Widget:
    w, d = await _widget(db, principal, widget_id, edit=True)
    _check_widget_mode(principal, d, body.mode or (w.mode if body.spec is not None else None))
    changes = body.model_dump(exclude_unset=True)
    for k, v in changes.items():
        setattr(w, k, v)
    if "observation" in changes:
        w.observation_author = principal.label
        w.observation_is_ai_draft = False
    await db.commit()
    await db.refresh(w)
    return w


@router.delete("/widgets/{widget_id}", status_code=204)
async def delete_widget(widget_id: uuid.UUID, principal: CurrentPrincipal, db: DB) -> Response:
    w, _ = await _widget(db, principal, widget_id, edit=True)
    await db.delete(w)
    await db.commit()
    return Response(status_code=204)


@router.put(
    "/dashboards/{dashboard_id}/layout", response_model=DashboardOut, summary="Save positions after drag & drop"
)
async def save_layout(
    dashboard_id: uuid.UUID, body: list[LayoutItem], principal: CurrentPrincipal, db: DB
) -> DashboardOut:
    d = await service.get_dashboard(db, principal, dashboard_id, edit=True)
    by_id = {w.id: w for w in d.widgets}
    for i, item in enumerate(sorted(body, key=lambda x: (x.layout.get("y", 0), x.layout.get("x", 0)))):
        if item.id in by_id:
            by_id[item.id].layout = item.layout
            by_id[item.id].position = i
    await db.commit()
    await db.refresh(d)
    return full(d, principal)


def _filters(body: DataIn) -> list[Filter]:
    return [Filter(f.dimension, f.op, tuple(f.values)) for f in body.filters]


async def _project_of(db: DB, d: Dashboard) -> Project | None:
    return await db.get(Project, d.project_id) if d.project_id else None


@router.post("/dashboards/{dashboard_id}/widgets/{widget_id}/data", response_model=DataOut)
async def widget_data(
    dashboard_id: uuid.UUID, widget_id: uuid.UUID, body: DataIn, principal: CurrentPrincipal, db: DB
) -> DataOut:
    d = await service.get_dashboard(db, principal, dashboard_id)
    w = next((x for x in d.widgets if x.id == widget_id), None)
    if w is None:
        raise NotFoundError("Блок не найден")
    return await _data(db, principal, d, w.mode, w.spec, body)


async def _data(db: DB, principal: Principal, d: Dashboard, mode: str, spec: dict, body: DataIn) -> DataOut:  # type: ignore[type-arg]
    date_from, date_to = service.effective_range(d, service.GlobalFilters(body.date_from, body.date_to))
    res = await service.widget_data(
        db, principal, await _project_of(db, d), mode, spec, date_from, date_to, _filters(body)
    )
    return DataOut(
        columns=res.columns, rows=res.rows, sql=res.sql, cached=res.cached, date_from=date_from, date_to=date_to
    )


@router.post("/widgets/preview", response_model=DataOut, summary="Data for an unsaved block (block editor)")
async def preview(body: PreviewIn, principal: CurrentPrincipal, db: DB) -> DataOut:
    project = await load_project(db, principal, body.project_id)
    tmp = Dashboard(
        org_id=principal.org_id,
        project_id=project.id if project else None,
        title="preview",
        filters={"period_days": 30},
    )
    if body.mode == "sql":
        _check_widget_mode(principal, tmp, "sql")
    return await _data(db, principal, tmp, body.mode, body.spec, body)


# ------------------------------------------------------------------ sharing
@router.post("/dashboards/{dashboard_id}/share", response_model=ShareOut, summary="Public read-only link with expiry")
async def share(dashboard_id: uuid.UUID, body: ShareIn, principal: CurrentPrincipal, db: DB) -> ShareOut:
    d = await service.get_dashboard(db, principal, dashboard_id, edit=True)
    d.share_token = secrets.token_urlsafe(24)
    d.share_expires_at = datetime.now(UTC) + timedelta(days=body.ttl_days)
    await record(
        db,
        "dashboard.shared",
        principal=principal,
        resource_type="dashboard",
        resource_id=d.id,
        project_id=d.project_id,
        details={"ttl_days": body.ttl_days},
    )
    await db.commit()
    return ShareOut(token=d.share_token, expires_at=d.share_expires_at)


@router.delete("/dashboards/{dashboard_id}/share", status_code=204)
async def unshare(dashboard_id: uuid.UUID, principal: CurrentPrincipal, db: DB) -> Response:
    d = await service.get_dashboard(db, principal, dashboard_id, edit=True)
    d.share_token = None
    d.share_expires_at = None
    await record(db, "dashboard.unshared", principal=principal, resource_type="dashboard", resource_id=d.id)
    await db.commit()
    return Response(status_code=204)


@router.post("/dashboards/{dashboard_id}/grants", status_code=204, summary="Give a guest access to this dashboard")
async def grant(dashboard_id: uuid.UUID, body: GrantIn, principal: CurrentPrincipal, db: DB) -> Response:
    d = await service.get_dashboard(db, principal, dashboard_id, edit=True)
    user = await db.get(User, body.user_id)
    if user is None or user.org_id != principal.org_id:
        raise NotFoundError("Пользователь не найден")
    db.add(DashboardGrant(dashboard_id=d.id, user_id=user.id, expires_at=body.expires_at))
    await record(
        db,
        "dashboard.grant",
        principal=principal,
        resource_type="dashboard",
        resource_id=d.id,
        details={"user": user.email, "expires_at": str(body.expires_at or "")},
    )
    await db.commit()
    return Response(status_code=204)


async def _shared(db: DB, token: str) -> tuple[Dashboard, Principal]:
    d = (await db.execute(select(Dashboard).where(Dashboard.share_token == token))).scalar_one_or_none()
    if d is None or not d.share_expires_at or d.share_expires_at < datetime.now(UTC) or d.owner_id is None:
        raise NotFoundError("Ссылка недействительна или истекла")
    owner = await db.get(User, d.owner_id)
    if owner is None or not owner.is_active:
        raise NotFoundError("Ссылка недействительна")
    # data is computed with the rights of the dashboard owner, restricted to this dashboard's widgets
    return d, build_principal(owner)


@router.get("/public/dashboards/{token}", response_model=DashboardOut, tags=["public"])
async def public_dashboard(token: str, db: DB) -> DashboardOut:
    d, _ = await _shared(db, token)
    out = full(d, None)
    out.owner_id = None
    return out


@router.post("/public/dashboards/{token}/widgets/{widget_id}/data", response_model=DataOut, tags=["public"])
async def public_widget_data(token: str, widget_id: uuid.UUID, body: DataIn, db: DB) -> DataOut:
    d, owner = await _shared(db, token)
    w = next((x for x in d.widgets if x.id == widget_id), None)
    if w is None:
        raise NotFoundError("Блок не найден")
    return await _data(db, owner, d, w.mode, w.spec, body)
