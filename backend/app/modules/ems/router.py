"""Event registry API (EMS)."""

from __future__ import annotations

import io
import json
import uuid
import zipfile
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, Literal

import sqlglot
from fastapi import APIRouter, Depends, Form, Query, Response, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select

from app.core.crypto import encrypt_json
from app.core.errors import NotFoundError, ValidationFailed
from app.modules.ai import documents
from app.modules.audit.service import record
from app.modules.connectors.models import DataSource
from app.modules.connectors.service import get_source, pool
from app.modules.ems import ai_drafts, codegen, semver, service, validation
from app.modules.ems.models import (
    Alert,
    Event,
    EventComment,
    EventVersion,
    GlobalParam,
    NotificationChannel,
    TrackingConfig,
    TrackingDraft,
    TrackingDraftItem,
    ValidationRun,
)
from app.modules.ems.notify import Notifier
from app.modules.ems.schemas import (
    AlertOut,
    ChannelIn,
    ChannelOut,
    DiffOut,
    DiscoverApplyIn,
    DiscoveredEvent,
    EventCommentIn,
    EventCommentOut,
    EventIn,
    EventOut,
    EventPatch,
    EventSummary,
    EventVersionOut,
    GlobalParamIn,
    GlobalParamOut,
    Governance,
    ImportOut,
    ParamIn,
    ReviewIn,
    StatPoint,
    StatusIn,
    TrackingDraftItemOut,
    TrackingDraftItemPatch,
    TrackingDraftOut,
    TrackingDraftSummary,
    TrackingIn,
    TrackingOut,
    ValidationRunOut,
    VersionIn,
)
from app.modules.iam.deps import DB, CurrentPrincipal, require
from app.modules.iam.models import Project
from app.modules.iam.permissions import P
from app.modules.iam.policy import Principal
from app.modules.query import service as query_service
from app.modules.query.service import load_project

router = APIRouter(prefix="/ems", tags=["events"])
channels_router = APIRouter(prefix="/notification-channels", tags=["notifications"])
Lang = Literal["json_schema", "typescript", "kotlin", "swift", "csharp"]
EXT = {"json_schema": "json", "typescript": "ts", "kotlin": "kt", "swift": "swift", "csharp": "cs"}


async def _project(db: DB, principal: Principal, project_id: uuid.UUID, permission: str = P.EVENTS_VIEW) -> Project:
    project = await load_project(db, principal, project_id)
    assert project is not None
    principal.require(permission, project.id)
    return project


async def _last_run(db: DB, project_id: uuid.UUID) -> ValidationRun | None:
    q = select(ValidationRun).where(ValidationRun.project_id == project_id, ValidationRun.status != "error")
    return (await db.execute(q.order_by(ValidationRun.started_at.desc()).limit(1))).scalar_one_or_none()


@router.get("/events", response_model=list[EventSummary])
async def list_events(
    principal: CurrentPrincipal, db: DB, project_id: uuid.UUID, status: str | None = None, q: str | None = None
) -> list[EventSummary]:
    await _project(db, principal, project_id)
    stmt = select(Event).where(Event.project_id == project_id)
    if status:
        stmt = stmt.where(Event.status == status)
    if q:
        stmt = stmt.where(Event.name.ilike(f"%{q}%") | Event.description.ilike(f"%{q}%"))
    events = list((await db.execute(stmt.order_by(Event.name))).scalars())
    pending = dict(
        (
            await db.execute(
                select(EventVersion.event_id, EventVersion.version).where(EventVersion.status == "pending")
            )
        ).all()
    )
    alerts = dict(
        (
            await db.execute(
                select(Alert.event_id, func.count())
                .where(Alert.project_id == project_id, Alert.status.in_(("open", "acknowledged")))
                .group_by(Alert.event_id)
            )
        ).all()
    )
    run = await _last_run(db, project_id)
    health = {r["event"]: r for r in (run.results if run else [])}
    out = []
    for e in events:
        s = EventSummary.model_validate(e)
        s.pending_version = pending.get(e.id)
        s.open_alerts = int(alerts.get(e.id, 0))
        if e.name in health:
            s.health, s.last_count = health[e.name]["status"], health[e.name]["count"]
        out.append(s)
    return out


async def _event_out(db: DB, principal: Principal, ev: Event) -> EventOut:
    versions = await service.versions_of(db, ev.id)
    comments = (
        await db.execute(select(EventComment).where(EventComment.event_id == ev.id).order_by(EventComment.created_at))
    ).scalars()
    base = EventSummary.model_validate(ev).model_dump()
    base["pending_version"] = next((v.version for v in versions if v.status == "pending"), None)
    run = await _last_run(db, ev.project_id)
    res = next((r for r in (run.results if run else []) if r["event"] == ev.name), None)
    if res:
        base["health"], base["last_count"] = res["status"], res["count"]
    return EventOut(
        **base,
        goal=ev.goal,
        question=ev.question,
        created_by=ev.created_by,
        versions=[EventVersionOut.model_validate(v) for v in versions],
        comments=[EventCommentOut.model_validate(c) for c in comments],
    )


@router.post("/events", response_model=EventOut, status_code=201, summary="Register an event (draft v1.0.0)")
async def create_event(body: EventIn, principal: CurrentPrincipal, db: DB) -> EventOut:
    project = await _project(db, principal, body.project_id)
    ev, _ = await service.create_event(
        db,
        principal,
        project,
        name=body.name,
        description=body.description,
        category=body.category,
        owner=body.owner,
        goal=body.goal,
        question=body.question,
        metric_keys=body.metric_keys,
        tags=body.tags,
        params=[p.model_dump() for p in body.params],
        app_version=body.app_version,
    )
    await db.commit()
    return await _event_out(db, principal, ev)


@router.get("/events/{event_id}", response_model=EventOut)
async def read_event(event_id: uuid.UUID, principal: CurrentPrincipal, db: DB) -> EventOut:
    return await _event_out(db, principal, await service.get_event(db, principal, event_id))


@router.patch("/events/{event_id}", response_model=EventOut)
async def update_event(event_id: uuid.UUID, body: EventPatch, principal: CurrentPrincipal, db: DB) -> EventOut:
    ev = await service.get_event(db, principal, event_id, P.EVENTS_EDIT)
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(ev, k, v)
    await db.commit()
    await db.refresh(ev)
    return await _event_out(db, principal, ev)


@router.post(
    "/events/{event_id}/versions",
    response_model=EventVersionOut,
    status_code=201,
    summary="Propose a new version (semver bump is computed from the diff)",
)
async def propose(event_id: uuid.UUID, body: VersionIn, principal: CurrentPrincipal, db: DB) -> EventVersion:
    ev = await service.get_event(db, principal, event_id, P.EVENTS_EDIT)
    v = await service.propose_version(
        db,
        principal,
        ev,
        [p.model_dump() for p in body.params],
        description=body.description,
        changelog=body.changelog,
        app_version=body.app_version,
    )
    await db.commit()
    await db.refresh(v)
    return v


@router.post("/events/{event_id}/versions/{version_id}/review", response_model=EventOut)
async def review(
    event_id: uuid.UUID, version_id: uuid.UUID, body: ReviewIn, principal: CurrentPrincipal, db: DB
) -> EventOut:
    ev = await service.get_event(db, principal, event_id)
    await service.review(db, principal, ev, version_id, body.approve, body.comment)
    await db.commit()
    await db.refresh(ev)
    return await _event_out(db, principal, ev)


@router.post("/events/{event_id}/status", response_model=EventOut, summary="Lifecycle: active ↔ deprecated → archived")
async def set_status(event_id: uuid.UUID, body: StatusIn, principal: CurrentPrincipal, db: DB) -> EventOut:
    ev = await service.get_event(db, principal, event_id)
    await service.change_status(db, principal, ev, body.status, body.reason)
    await db.commit()
    await db.refresh(ev)
    return await _event_out(db, principal, ev)


@router.get("/events/{event_id}/diff", response_model=DiffOut, summary="Diff of any two versions")
async def version_diff(
    event_id: uuid.UUID,
    principal: CurrentPrincipal,
    db: DB,
    from_version: Annotated[str, Query(alias="from")],
    to_version: Annotated[str, Query(alias="to")],
) -> DiffOut:
    await service.get_event(db, principal, event_id)
    versions = {v.version: v for v in await service.versions_of(db, event_id)}
    if from_version not in versions or to_version not in versions:
        raise NotFoundError("Версия не найдена")
    d = semver.diff(versions[from_version].params, versions[to_version].params)
    return DiffOut(from_version=from_version, to_version=to_version, **d.as_dict())


@router.post("/events/{event_id}/comments", response_model=EventCommentOut, status_code=201)
async def comment(event_id: uuid.UUID, body: EventCommentIn, principal: CurrentPrincipal, db: DB) -> EventComment:
    ev = await service.get_event(db, principal, event_id, P.EVENTS_COMMENT)
    c = EventComment(event_id=ev.id, author=principal.label, text=body.text)
    db.add(c)
    await db.commit()
    await db.refresh(c)
    return c


@router.get("/events/{event_id}/stats", response_model=list[StatPoint], summary="Daily volume by platform (monitoring)")
async def stats(
    event_id: uuid.UUID, principal: CurrentPrincipal, db: DB, days: Annotated[int, Query(ge=1, le=90)] = 14
) -> list[StatPoint]:
    ev = await service.get_event(db, principal, event_id)
    cfg = await db.get(TrackingConfig, ev.project_id)
    if cfg is None:
        return []
    source = await db.get(DataSource, cfg.source_id)
    project = await db.get(Project, ev.project_id)
    if source is None or project is None:
        return []

    def c(n: str) -> str:
        return service.quoted(cfg, n)

    name = ev.name.replace("'", "''")
    sql = (
        f"SELECT CAST({c('date_column')} AS DATE), {c('platform_column')}, COUNT(*) FROM {cfg.table} "
        f"WHERE {c('name_column')} = '{name}' AND {c('date_column')} >= CURRENT_DATE - INTERVAL '{days} day' GROUP BY 1, 2 ORDER BY 1, 2"
    )
    native = sqlglot.transpile(sql, read="postgres", write=(await pool.get(source)).dialect)[0]
    out = await query_service.execute(db, principal, source, project, native, origin="ems")
    return [StatPoint(date=str(d)[:10], platform=str(p), count=int(n)) for d, p, n in out.rows]


# ------------------------------------------------------------------ exports
@router.get("/export", summary="JSON Schema or generated code for all approved events of a project")
async def export(principal: CurrentPrincipal, db: DB, project_id: uuid.UUID, format: Lang = "json_schema") -> Response:
    project = await _project(db, principal, project_id, P.EVENTS_DOWNLOAD)
    events = (
        await db.execute(
            select(Event)
            .where(Event.project_id == project.id, Event.status == "active", Event.current_version.is_not(None))
            .order_by(Event.name)
        )
    ).scalars()
    views = []
    for e in events:
        v = (
            await db.execute(
                select(EventVersion).where(EventVersion.event_id == e.id, EventVersion.version == e.current_version)
            )
        ).scalar_one()
        views.append(service.export_view(e, v, project.key))
    gp = [
        {"name": g.name, "type": g.type, "required": g.required, "description": g.description, "enum": g.enum}
        for g in await service.global_params(db, principal.org_id)
    ]
    await record(
        db, "event.export", principal=principal, project_id=project.id, details={"format": format, "events": len(views)}
    )
    await db.commit()
    filename = f"{project.key}_events.{EXT[format]}"
    if format == "json_schema":
        body = json.dumps(
            {v["name"]: codegen.json_schema(v, v["params"], gp) for v in views}, ensure_ascii=False, indent=2
        )
        media = "application/json"
    else:
        body = codegen.generate(format, views, namespace="".join(p.capitalize() for p in project.key.split("_")))
        media = "text/plain; charset=utf-8"
    return Response(body, media_type=media, headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@router.get("/export/bundle", summary="ZIP with JSON Schema and code for every supported language")
async def export_bundle(principal: CurrentPrincipal, db: DB, project_id: uuid.UUID) -> StreamingResponse:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for fmt in EXT:
            resp = await export(principal, db, project_id, fmt)  # type: ignore[arg-type]
            zf.writestr(resp.headers["content-disposition"].split('filename="')[1].rstrip('"'), bytes(resp.body))
    buf.seek(0)
    return StreamingResponse(
        buf, media_type="application/zip", headers={"Content-Disposition": 'attachment; filename="events.zip"'}
    )


# ------------------------------------------------------------------ import & discovery
@router.get("/import/template", summary="CSV template of a tracking plan")
async def import_template(_: CurrentPrincipal) -> Response:
    csv = (
        "event_name,event_description,param_name,param_type,required,param_description,enum\n"
        "level_complete,Уровень пройден,level,int,true,Номер уровня,\n"
        "level_complete,,mode,string,false,Режим,pve;pvp\n"
    )
    return Response(
        "﻿" + csv,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="tracking_plan.csv"'},
    )


@router.post(
    "/import", response_model=ImportOut, summary="Import an existing tracking plan (CSV/XLSX export of Sheets/Excel)"
)
async def import_plan(
    file: UploadFile, principal: CurrentPrincipal, db: DB, project_id: uuid.UUID, app_version: str = ""
) -> ImportOut:
    project = await _project(db, principal, project_id, P.EVENTS_EDIT)
    content = await file.read(10 * 1024 * 1024 + 1)
    if len(content) > 10 * 1024 * 1024:
        raise ValidationFailed("Файл больше 10 МБ")
    plan = service.parse_tracking_plan(file.filename or "plan.csv", content)
    res = await service.import_plan(db, principal, project, plan, app_version)
    await db.commit()
    return ImportOut(**res)


@router.get("/discover", response_model=list[DiscoveredEvent], summary="Describe events automatically from actual data")
async def discover(
    principal: CurrentPrincipal, db: DB, project_id: uuid.UUID, days: Annotated[int, Query(ge=1, le=30)] = 3
) -> list[DiscoveredEvent]:
    project = await _project(db, principal, project_id, P.EVENTS_EDIT)
    cfg = await db.get(TrackingConfig, project.id)
    if cfg is None:
        raise ValidationFailed("Сначала укажите источник событий проекта")
    source = await get_source(db, principal, cfg.source_id)
    dialect = (await pool.get(source)).dialect

    def q(n: str) -> str:
        return service.quoted(cfg, n)

    since = f"CAST((SELECT MAX({q('date_column')}) FROM {cfg.table}) - INTERVAL '{days} day' AS DATE)"
    counts_sql = f"SELECT {q('name_column')}, COUNT(*) FROM {cfg.table} WHERE {q('date_column')} >= {since} GROUP BY 1 ORDER BY 2 DESC"
    sample_sql = f"SELECT {q('name_column')}, {q('params_column')} FROM {cfg.table} WHERE {q('date_column')} >= {since}"

    async def run(sql: str, limit: int) -> query_service.QueryOutcome:
        native = sqlglot.transpile(sql, read="postgres", write=dialect)[0]
        return await query_service.execute(db, principal, source, project, native, origin="ems", limit=limit)

    counts = (await run(counts_sql, 1000)).rows
    sample = (await run(sample_sql, 50_000)).rows
    by_event: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for name, raw in sample:
        if len(by_event[str(name)]) < 1000:
            by_event[str(name)].append(service.parse_params(raw))
    registered = set((await db.execute(select(Event.name).where(Event.project_id == project.id))).scalars())
    return [
        DiscoveredEvent(
            name=str(n),
            count=int(c),
            registered=str(n) in registered,
            params=[ParamIn(**p) for p in service.infer_params(by_event.get(str(n), []))],
        )
        for n, c in counts
    ]


@router.post("/discover/apply", response_model=ImportOut, summary="Create drafts for discovered events")
async def discover_apply(body: DiscoverApplyIn, principal: CurrentPrincipal, db: DB) -> ImportOut:
    project = await _project(db, principal, body.project_id, P.EVENTS_EDIT)
    plan = {
        e.name: {
            "description": "Описано автоматически по фактическим данным",
            "params": [p.model_dump() for p in e.params],
        }
        for e in body.events
        if not e.registered
    }
    res = await service.import_plan(db, principal, project, plan)
    await db.commit()
    return ImportOut(**res)


# ------------------------------------------------------------------ validation, alerts, governance
@router.get("/tracking/{project_id}", response_model=TrackingOut | None)
async def get_tracking(project_id: uuid.UUID, principal: CurrentPrincipal, db: DB) -> TrackingConfig | None:
    await _project(db, principal, project_id)
    return await db.get(TrackingConfig, project_id)


@router.put("/tracking/{project_id}", response_model=TrackingOut)
async def put_tracking(project_id: uuid.UUID, body: TrackingIn, principal: CurrentPrincipal, db: DB) -> TrackingConfig:
    project = await _project(db, principal, project_id, P.EVENTS_APPROVE)
    await get_source(db, principal, body.source_id)
    cfg = await db.get(TrackingConfig, project.id) or TrackingConfig(project_id=project.id)
    for k, v in body.model_dump().items():
        setattr(cfg, k, v)
    db.add(cfg)
    await db.commit()
    await db.refresh(cfg)
    return cfg


@router.post("/validate/{project_id}", response_model=ValidationRunOut, summary="Run post-release validation now")
async def validate_now(project_id: uuid.UUID, principal: CurrentPrincipal, db: DB) -> ValidationRun:
    project = await _project(db, principal, project_id, P.EVENTS_EDIT)
    run = await validation.run_validation(db, project)
    await record(db, "ems.validation_run", principal=principal, project_id=project.id, details={"status": run.status})
    await db.commit()
    return run


@router.get("/runs", response_model=list[ValidationRunOut])
async def runs(
    principal: CurrentPrincipal, db: DB, project_id: uuid.UUID, limit: Annotated[int, Query(le=50)] = 10
) -> list[ValidationRun]:
    await _project(db, principal, project_id)
    q = (
        select(ValidationRun)
        .where(ValidationRun.project_id == project_id)
        .order_by(ValidationRun.started_at.desc())
        .limit(limit)
    )
    return list((await db.execute(q)).scalars())


@router.get("/alerts", response_model=list[AlertOut])
async def alerts(
    principal: CurrentPrincipal,
    db: DB,
    project_id: uuid.UUID,
    status: str = "active",
    limit: Annotated[int, Query(le=500)] = 100,
) -> list[Alert]:
    await _project(db, principal, project_id)
    q = select(Alert).where(Alert.project_id == project_id)
    if status == "active":
        q = q.where(Alert.status.in_(("open", "acknowledged")))
    elif status != "all":
        q = q.where(Alert.status == status)
    return list((await db.execute(q.order_by(Alert.created_at.desc()).limit(limit))).scalars())


@router.post("/alerts/{alert_id}/{action}", response_model=AlertOut)
async def alert_action(
    alert_id: uuid.UUID, action: Literal["ack", "resolve", "reopen"], principal: CurrentPrincipal, db: DB
) -> Alert:
    alert = await db.get(Alert, alert_id)
    if alert is None or alert.org_id != principal.org_id:
        raise NotFoundError("Алерт не найден")
    await _project(db, principal, alert.project_id, P.EVENTS_EDIT)
    if action == "ack":
        alert.status, alert.acknowledged_by = "acknowledged", principal.label
    elif action == "resolve":
        alert.status, alert.resolved_at = "resolved", datetime.now(UTC)
    else:
        alert.status, alert.resolved_at = "open", None
    await record(
        db,
        f"alert.{action}",
        principal=principal,
        resource_type="alert",
        resource_id=alert.id,
        project_id=alert.project_id,
    )
    await db.commit()
    await db.refresh(alert)
    return alert


@router.get(
    "/governance",
    response_model=Governance,
    summary="Events without owner/metric, deprecated still firing, unregistered",
)
async def governance(principal: CurrentPrincipal, db: DB, project_id: uuid.UUID) -> Governance:
    await _project(db, principal, project_id)
    events = list((await db.execute(select(Event).where(Event.project_id == project_id))).scalars())
    run = await _last_run(db, project_id)
    results = {r["event"]: r for r in (run.results if run else [])}
    pending = set(
        (
            await db.execute(
                select(Event.name)
                .join(EventVersion, EventVersion.event_id == Event.id)
                .where(Event.project_id == project_id, EventVersion.status == "pending")
            )
        ).scalars()
    )
    month_ago = datetime.now(UTC) - timedelta(days=30)
    live = [e for e in events if e.status in ("active", "deprecated")]
    return Governance(
        no_owner=[e.name for e in live if not e.owner],
        no_metrics=[e.name for e in live if not e.metric_keys],
        deprecated_firing=[
            e.name for e in events if e.status == "deprecated" and (results.get(e.name, {}).get("count") or 0) > 0
        ],
        unregistered=list((run.summary or {}).get("unregistered_events", [])) if run else [],
        pending_review=sorted(pending),
        stale_drafts=[e.name for e in events if e.status == "draft" and e.created_at < month_ago],
    )


# ------------------------------------------------------------------ global parameters
@router.get("/global-params", response_model=list[GlobalParamOut])
async def list_global(principal: CurrentPrincipal, db: DB) -> list[GlobalParam]:
    return await service.global_params(db, principal.org_id)


@router.put("/global-params", response_model=list[GlobalParamOut], summary="Replace the global parameter library")
async def put_global(body: list[GlobalParamIn], principal: CurrentPrincipal, db: DB) -> list[GlobalParam]:
    if not principal.can_anywhere(P.EVENTS_APPROVE):
        principal.require(P.EVENTS_APPROVE)
    clean = semver.normalize_params([p.model_dump() for p in body])
    for g in await service.global_params(db, principal.org_id):
        await db.delete(g)
    await db.flush()
    for p in clean:
        db.add(GlobalParam(org_id=principal.org_id, **p))
    await record(db, "ems.global_params_updated", principal=principal, details={"params": [p["name"] for p in clean]})
    await db.commit()
    return await service.global_params(db, principal.org_id)


# ------------------------------------------------------------------ notification channels (admin)
ChannelAdmin = Annotated[Principal, Depends(require(P.ADMIN_PROJECTS))]


def _channel_out(c: NotificationChannel) -> ChannelOut:
    out = ChannelOut.model_validate(c)
    out.has_secrets = bool(c.secrets_encrypted)
    return out


@channels_router.get("", response_model=list[ChannelOut])
async def list_channels(principal: ChannelAdmin, db: DB) -> list[ChannelOut]:
    q = (
        select(NotificationChannel)
        .where(NotificationChannel.org_id == principal.org_id)
        .order_by(NotificationChannel.name)
    )
    return [_channel_out(c) for c in (await db.execute(q)).scalars()]


REQUIRED_SECRETS = {"slack": ("webhook_url",), "mattermost": ("webhook_url",), "telegram": ("bot_token",), "email": ()}


@channels_router.post("", response_model=ChannelOut, status_code=201)
async def create_channel(body: ChannelIn, principal: ChannelAdmin, db: DB) -> ChannelOut:
    missing = [k for k in REQUIRED_SECRETS[body.kind] if not body.secrets.get(k)]
    if body.kind == "telegram" and not body.config.get("chat_id"):
        missing.append("chat_id")
    if body.kind == "email" and not (body.config.get("host") and body.config.get("from") and body.config.get("to")):
        missing.append("host/from/to")
    if missing:
        raise ValidationFailed("Не заполнены поля канала", details={"missing": missing})
    c = NotificationChannel(
        org_id=principal.org_id,
        name=body.name,
        kind=body.kind,
        config=body.config,
        secrets_encrypted=encrypt_json(body.secrets) if body.secrets else None,
        min_severity=body.min_severity,
        project_ids=body.project_ids,
        enabled=body.enabled,
    )
    db.add(c)
    await db.flush()
    await record(
        db,
        "channel.create",
        principal=principal,
        resource_type="notification_channel",
        resource_id=c.id,
        details={"kind": body.kind},
    )
    await db.commit()
    return _channel_out(c)


@channels_router.delete("/{channel_id}", status_code=204)
async def delete_channel(channel_id: uuid.UUID, principal: ChannelAdmin, db: DB) -> Response:
    c = await db.get(NotificationChannel, channel_id)
    if c is None or c.org_id != principal.org_id:
        raise NotFoundError("Канал не найден")
    await db.delete(c)
    await db.commit()
    return Response(status_code=204)


@channels_router.post("/{channel_id}/test", status_code=204, summary="Send a test message")
async def test_channel(channel_id: uuid.UUID, principal: ChannelAdmin, db: DB) -> Response:
    c = await db.get(NotificationChannel, channel_id)
    if c is None or c.org_id != principal.org_id:
        raise NotFoundError("Канал не найден")
    try:
        await Notifier.send(c, "✅ Тестовое сообщение аналитической платформы", "Тест уведомлений")
    except Exception as exc:
        raise ValidationFailed(f"Не удалось отправить: {exc}") from exc
    return Response(status_code=204)


# ---------------------------------------------------------------- AI tracking plan drafts
async def _draft_out(db: DB, draft: TrackingDraft) -> TrackingDraftOut:
    items = await ai_drafts.items_of(db, draft.id)
    out_items = []
    for it in items:
        o = TrackingDraftItemOut.model_validate(it)
        if it.action == "update" and it.event_id:
            versions = await service.versions_of(db, it.event_id)
            base = service.latest_approved(versions)
            o.diff = semver.diff(base.params if base else [], it.params).as_dict()
        out_items.append(o)
    counts = {s: sum(1 for i in items if i.status == s) for s in ("pending", "accepted", "rejected")}
    return TrackingDraftOut(
        **TrackingDraftSummary.model_validate(draft).model_dump(exclude=set(counts)),
        **counts,
        truncated=draft.truncated,
        source_text=draft.source_text,
        items=out_items,
    )


@router.post(
    "/ai-drafts",
    response_model=TrackingDraftOut,
    status_code=201,
    summary="AI proposes events from a release document (file or pasted text)",
)
async def create_ai_draft(
    principal: CurrentPrincipal,
    db: DB,
    project_id: Annotated[uuid.UUID, Form()],
    file: UploadFile | None = None,
    text: Annotated[str, Form()] = "",
    title: Annotated[str, Form()] = "",
    app_version: Annotated[str, Form()] = "",
) -> TrackingDraftOut:
    project = await _project(db, principal, project_id, P.EVENTS_EDIT)
    if file is not None and file.filename:
        content = await file.read(documents.MAX_BYTES + 1)
        body, truncated = documents.extract_text(file.filename, content)
        filename = file.filename
    elif text.strip():
        body, truncated = text.strip()[: documents.MAX_CHARS], len(text.strip()) > documents.MAX_CHARS
        filename = ""
    else:
        raise ValidationFailed("Приложите документ или вставьте текст")
    title = title.strip() or filename or body.split("\n", 1)[0][:120]
    draft = await ai_drafts.create_draft(
        db,
        principal,
        project,
        title=title,
        filename=filename,
        text=body,
        truncated=truncated,
        app_version=app_version.strip(),
    )
    return await _draft_out(db, draft)


@router.get("/ai-drafts", response_model=list[TrackingDraftSummary])
async def list_ai_drafts(principal: CurrentPrincipal, db: DB, project_id: uuid.UUID) -> list[TrackingDraftSummary]:
    await _project(db, principal, project_id)
    drafts = (
        await db.execute(
            select(TrackingDraft)
            .where(TrackingDraft.project_id == project_id)
            .order_by(TrackingDraft.created_at.desc())
        )
    ).scalars()
    out = []
    for d in drafts:
        rows = dict(
            (
                await db.execute(
                    select(TrackingDraftItem.status, func.count())
                    .where(TrackingDraftItem.draft_id == d.id)
                    .group_by(TrackingDraftItem.status)
                )
            ).all()
        )
        out.append(
            TrackingDraftSummary.model_validate(d).model_copy(
                update={k: int(rows.get(k, 0)) for k in ("pending", "accepted", "rejected")}
            )
        )
    return out


@router.get("/ai-drafts/{draft_id}", response_model=TrackingDraftOut)
async def get_ai_draft(draft_id: uuid.UUID, principal: CurrentPrincipal, db: DB) -> TrackingDraftOut:
    return await _draft_out(db, await ai_drafts.get_draft(db, principal, draft_id))


@router.patch(
    "/ai-drafts/{draft_id}/items/{item_id}", response_model=TrackingDraftOut, summary="Edit a proposal before accepting"
)
async def update_ai_draft_item(
    draft_id: uuid.UUID, item_id: uuid.UUID, body: TrackingDraftItemPatch, principal: CurrentPrincipal, db: DB
) -> TrackingDraftOut:
    draft = await ai_drafts.get_draft(db, principal, draft_id)
    changes = body.model_dump(exclude_unset=True)
    if "params" in changes:
        changes["params"] = [p.model_dump() for p in body.params or []]
    await ai_drafts.update_item(db, principal, draft, item_id, changes)
    return await _draft_out(db, draft)


@router.post(
    "/ai-drafts/{draft_id}/items/{item_id}/{decision}",
    response_model=TrackingDraftOut,
    summary="Accept (creates a registry draft / pending version) or reject a proposal",
)
async def decide_ai_draft_item(
    draft_id: uuid.UUID, item_id: uuid.UUID, decision: Literal["accept", "reject"], principal: CurrentPrincipal, db: DB
) -> TrackingDraftOut:
    draft = await ai_drafts.get_draft(db, principal, draft_id)
    if decision == "accept":
        await ai_drafts.accept(db, principal, draft, item_id)
    else:
        await ai_drafts.reject(db, principal, draft, item_id)
    return await _draft_out(db, draft)
