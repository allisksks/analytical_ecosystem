"""SQL editor API: run with access rules, cancel, export, history, saved queries; RLS rules admin."""

from __future__ import annotations

import csv
import io
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response
from fastapi.responses import StreamingResponse
from openpyxl import Workbook
from sqlalchemy import ColumnElement, or_, select

from app.core.errors import NotFoundError
from app.modules.audit.service import record
from app.modules.connectors.service import get_source
from app.modules.iam.deps import DB, CurrentPrincipal, require
from app.modules.iam.permissions import P
from app.modules.iam.policy import Principal
from app.modules.query import service
from app.modules.query.models import QueryRun, RlsRule, SavedQuery
from app.modules.query.schemas import (
    ExportIn,
    HistoryOut,
    RlsRuleIn,
    RlsRuleOut,
    RunIn,
    RunOut,
    SavedQueryIn,
    SavedQueryOut,
    SavedQueryPatch,
)

router = APIRouter(tags=["query"])
EXPORT_LIMIT = 100_000


async def _run(db: DB, principal: Principal, body: RunIn, limit: int | None = None) -> service.QueryOutcome:
    source = await get_source(db, principal, body.source_id)
    project = await service.load_project(db, principal, body.project_id)
    service.check_sql_access(principal, source, project)
    return await service.execute(
        db,
        principal,
        source,
        project,
        body.sql,
        origin="sql_editor",
        limit=limit or body.limit,
        use_cache=body.use_cache,
        query_id=body.query_id,
    )


@router.post("/query/run", response_model=RunOut, summary="Run a read-only SQL query")
async def run(body: RunIn, principal: CurrentPrincipal, db: DB) -> RunOut:
    out = await _run(db, principal, body)
    return RunOut.model_validate(out, from_attributes=True)


@router.post("/query/{query_id}/cancel", status_code=204)
async def cancel(query_id: str, principal: CurrentPrincipal) -> Response:
    await service.cancel(principal, query_id)
    return Response(status_code=204)


@router.post("/query/export", summary="Run and download the result as CSV or XLSX")
async def export(body: ExportIn, principal: CurrentPrincipal, db: DB) -> StreamingResponse:
    out = await _run(db, principal, body, limit=EXPORT_LIMIT)
    await record(
        db,
        "query.export",
        principal=principal,
        resource_type="data_source",
        resource_id=body.source_id,
        project_id=body.project_id,
        row_count=out.row_count,
        details={"format": body.format},
    )
    await db.commit()
    header = [c["name"] for c in out.columns]
    if body.format == "xlsx":
        wb = Workbook(write_only=True)
        ws = wb.create_sheet("result")
        ws.append(header)
        for row in out.rows:
            ws.append([v if not isinstance(v, (list, dict)) else str(v) for v in row])
        buf = io.BytesIO()
        wb.save(buf)
        buf.seek(0)
        media = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        return StreamingResponse(
            buf, media_type=media, headers={"Content-Disposition": 'attachment; filename="result.xlsx"'}
        )
    text = io.StringIO()
    writer = csv.writer(text)
    writer.writerow(header)
    writer.writerows(out.rows)
    data = "﻿" + text.getvalue()  # BOM: Excel opens UTF-8 correctly
    return StreamingResponse(
        iter([data.encode()]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="result.csv"'},
    )


@router.get("/query/history", response_model=list[HistoryOut])
async def history(
    principal: CurrentPrincipal,
    db: DB,
    source_id: uuid.UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[QueryRun]:
    q = select(QueryRun).where(QueryRun.user_id == principal.id, QueryRun.origin == "sql_editor")
    if source_id:
        q = q.where(QueryRun.source_id == source_id)
    return list((await db.execute(q.order_by(QueryRun.created_at.desc()).limit(limit))).scalars())


# ---------------------------------------------------------------- saved queries
def _visible_saved(principal: Principal) -> list[ColumnElement[bool]]:
    projects = principal.visible_project_ids()
    cond = [
        SavedQuery.org_id == principal.org_id,
        or_(SavedQuery.owner_id == principal.id, SavedQuery.shared.is_(True)),
    ]
    if projects is not None:
        cond.append(or_(SavedQuery.project_id.is_(None), SavedQuery.project_id.in_(projects)))
    return cond


@router.get("/saved-queries", response_model=list[SavedQueryOut])
async def list_saved(principal: CurrentPrincipal, db: DB, project_id: uuid.UUID | None = None) -> list[SavedQuery]:
    q = select(SavedQuery).where(*_visible_saved(principal))
    if project_id:
        q = q.where(SavedQuery.project_id == project_id)
    return list((await db.execute(q.order_by(SavedQuery.updated_at.desc()))).scalars())


@router.post("/saved-queries", response_model=SavedQueryOut, status_code=201)
async def create_saved(body: SavedQueryIn, principal: CurrentPrincipal, db: DB) -> SavedQuery:
    source = await get_source(db, principal, body.source_id)
    project = await service.load_project(db, principal, body.project_id)
    service.check_sql_access(principal, source, project)
    sq = SavedQuery(org_id=principal.org_id, owner_id=principal.id, **body.model_dump())
    db.add(sq)
    await db.commit()
    await db.refresh(sq)
    return sq


async def _own_saved(db: DB, principal: Principal, sq_id: uuid.UUID) -> SavedQuery:
    sq = await db.get(SavedQuery, sq_id)
    if sq is None or sq.org_id != principal.org_id:
        raise NotFoundError("Запрос не найден")
    if sq.owner_id != principal.id:
        principal.require(P.DASHBOARDS_EDIT, sq.project_id)
    return sq


@router.patch("/saved-queries/{sq_id}", response_model=SavedQueryOut)
async def update_saved(sq_id: uuid.UUID, body: SavedQueryPatch, principal: CurrentPrincipal, db: DB) -> SavedQuery:
    sq = await _own_saved(db, principal, sq_id)
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(sq, k, v)
    await db.commit()
    await db.refresh(sq)
    return sq


@router.delete("/saved-queries/{sq_id}", status_code=204)
async def delete_saved(sq_id: uuid.UUID, principal: CurrentPrincipal, db: DB) -> Response:
    sq = await _own_saved(db, principal, sq_id)
    await db.delete(sq)
    await db.commit()
    return Response(status_code=204)


# ---------------------------------------------------------------- RLS rules (administrators)
RlsAdmin = Annotated[Principal, Depends(require(P.ADMIN_ROLES))]


@router.get("/admin/rls-rules", response_model=list[RlsRuleOut])
async def list_rls(principal: RlsAdmin, db: DB) -> list[RlsRule]:
    return list((await db.execute(select(RlsRule).where(RlsRule.org_id == principal.org_id))).scalars())


@router.post("/admin/rls-rules", response_model=RlsRuleOut, status_code=201)
async def create_rls(body: RlsRuleIn, principal: RlsAdmin, db: DB) -> RlsRule:
    rule = RlsRule(org_id=principal.org_id, **body.model_dump())
    db.add(rule)
    await db.flush()
    await record(
        db,
        "rls.create",
        principal=principal,
        resource_type="rls_rule",
        resource_id=rule.id,
        details=body.model_dump(mode="json"),
    )
    await db.commit()
    return rule


@router.delete("/admin/rls-rules/{rule_id}", status_code=204)
async def delete_rls(rule_id: uuid.UUID, principal: RlsAdmin, db: DB) -> Response:
    rule = await db.get(RlsRule, rule_id)
    if rule is None or rule.org_id != principal.org_id:
        raise NotFoundError("Правило не найдено")
    await db.delete(rule)
    await record(db, "rls.delete", principal=principal, resource_type="rls_rule", resource_id=rule_id)
    await db.commit()
    return Response(status_code=204)
