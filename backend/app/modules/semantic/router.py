"""Semantic layer API: metric/dimension catalogue with versions and the no-SQL query endpoint."""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from sqlalchemy import select

from app.core.errors import ConflictError, NotFoundError
from app.modules.audit.service import record
from app.modules.iam.deps import DB, CurrentPrincipal, require
from app.modules.iam.permissions import P
from app.modules.iam.policy import Principal
from app.modules.query.service import load_project
from app.modules.semantic import service
from app.modules.semantic.compiler import Filter, validate_metric
from app.modules.semantic.models import Dimension, Metric, MetricVersion
from app.modules.semantic.schemas import (
    DimensionIn,
    DimensionOut,
    InstallOut,
    MetricIn,
    MetricOut,
    MetricPatch,
    MetricVersionOut,
    SemanticQueryIn,
    SemanticResultOut,
)

router = APIRouter(prefix="/semantic", tags=["semantic"])


def _require_edit(principal: Principal) -> None:
    if not principal.can_anywhere(P.SEMANTIC_EDIT):
        principal.require(P.SEMANTIC_EDIT)


@router.get("/metrics", response_model=list[MetricOut])
async def list_metrics(principal: CurrentPrincipal, db: DB) -> list[Metric]:
    q = select(Metric).where(Metric.org_id == principal.org_id).order_by(Metric.pack, Metric.name)
    return list((await db.execute(q)).scalars())


@router.get("/dimensions", response_model=list[DimensionOut])
async def list_dimensions(principal: CurrentPrincipal, db: DB) -> list[Dimension]:
    return list(
        (
            await db.execute(select(Dimension).where(Dimension.org_id == principal.org_id).order_by(Dimension.name))
        ).scalars()
    )


@router.post("/dimensions", response_model=DimensionOut, status_code=201)
async def create_dimension(body: DimensionIn, principal: CurrentPrincipal, db: DB) -> Dimension:
    _require_edit(principal)
    if await db.scalar(select(Dimension.id).where(Dimension.org_id == principal.org_id, Dimension.key == body.key)):
        raise ConflictError("Измерение уже существует")
    d = Dimension(org_id=principal.org_id, **body.model_dump())
    db.add(d)
    await db.commit()
    return d


@router.post("/metrics", response_model=MetricOut, status_code=201)
async def create_metric(body: MetricIn, principal: CurrentPrincipal, db: DB) -> Metric:
    _require_edit(principal)
    if await db.scalar(select(Metric.id).where(Metric.org_id == principal.org_id, Metric.key == body.key)):
        raise ConflictError("Метрика с таким ключом уже существует")
    m = Metric(org_id=principal.org_id, version=1, **body.model_dump())
    validate_metric(service.metric_def(m))
    db.add(m)
    await db.flush()
    await service.add_version(db, m, principal.label)
    await record(
        db,
        "metric.create",
        principal=principal,
        resource_type="metric",
        resource_id=m.id,
        details={"key": m.key, "expression": m.expression},
    )
    await db.commit()
    await db.refresh(m)
    return m


async def _metric(db: DB, principal: Principal, metric_id: uuid.UUID) -> Metric:
    m = await db.get(Metric, metric_id)
    if m is None or m.org_id != principal.org_id:
        raise NotFoundError("Метрика не найдена")
    return m


@router.patch("/metrics/{metric_id}", response_model=MetricOut, summary="Change a metric (creates a new version)")
async def update_metric(metric_id: uuid.UUID, body: MetricPatch, principal: CurrentPrincipal, db: DB) -> Metric:
    _require_edit(principal)
    m = await _metric(db, principal, metric_id)
    changes = body.model_dump(exclude_unset=True)
    for k, v in changes.items():
        setattr(m, k, v)
    validate_metric(service.metric_def(m))
    m.version += 1
    await service.add_version(db, m, principal.label)
    await record(
        db,
        "metric.update",
        principal=principal,
        resource_type="metric",
        resource_id=m.id,
        details={"version": m.version, "changes": body.model_dump(mode="json", exclude_unset=True)},
    )
    await db.commit()
    await db.refresh(m)
    return m


@router.get("/metrics/{metric_id}/versions", response_model=list[MetricVersionOut])
async def metric_versions(metric_id: uuid.UUID, principal: CurrentPrincipal, db: DB) -> list[MetricVersion]:
    await _metric(db, principal, metric_id)
    q = select(MetricVersion).where(MetricVersion.metric_id == metric_id).order_by(MetricVersion.version.desc())
    return list((await db.execute(q)).scalars())


@router.post("/packs/{pack}/install", response_model=InstallOut, summary="Install a domain pack (metrics, dimensions)")
async def install(pack: str, principal: Annotated[Principal, Depends(require(P.ADMIN_PROJECTS))], db: DB) -> InstallOut:
    res = await service.install_pack(db, principal.org_id, pack, principal.label)
    await record(db, "semantic.pack_installed", principal=principal, details={"pack": pack, **res})
    await db.commit()
    return InstallOut(**res)


@router.get("/packs", response_model=list[str])
async def packs(_: CurrentPrincipal) -> list[str]:
    return service.available_packs()


@router.get("/dimensions/{key}/values", response_model=list[Any], summary="Distinct values for filter pickers")
async def dimension_values(
    key: str, principal: CurrentPrincipal, db: DB, project_id: uuid.UUID | None = None
) -> list[Any]:
    project = await load_project(db, principal, project_id)
    return await service.dimension_values(db, principal, project, key)


@router.post("/query", response_model=SemanticResultOut, summary="Run metrics by dimensions without SQL")
async def query(body: SemanticQueryIn, principal: CurrentPrincipal, db: DB) -> SemanticResultOut:
    project = await load_project(db, principal, body.project_id)
    req = to_request(body)
    res = await service.run(db, principal, project, req)
    return SemanticResultOut(columns=res.columns, rows=res.rows, sql=res.sql, cached=res.cached)


def to_request(body: SemanticQueryIn) -> service.SemanticRequest:
    return service.SemanticRequest(
        metrics=body.metrics,
        dimensions=body.dimensions,
        grain=body.grain,
        date_from=body.date_from,
        date_to=body.date_to,
        filters=[Filter(f.dimension, f.op, tuple(f.values)) for f in body.filters],
        cohorts=[
            service.Cohort(c.label, [Filter(f.dimension, f.op, tuple(f.values)) for f in c.filters])
            for c in body.cohorts
        ],
        limit=body.limit,
    )
