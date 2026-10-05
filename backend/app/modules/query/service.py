"""Query Service: access check -> guard (RLS, PII masking, limit) -> cache -> source -> audit.

Used by the SQL editor, dashboards, the semantic layer, experiments and the AI assistant alike,
so access rules are enforced in exactly one place.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import math
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, time
from decimal import Decimal
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.errors import AppError, NotFoundError, PermissionDenied
from app.modules.audit.service import record
from app.modules.connectors.base import ConnectorError, QueryCancelled, QueryTimeout
from app.modules.connectors.models import DataSource
from app.modules.connectors.service import catalog_index, pool, source_allowed_in
from app.modules.iam.models import Project
from app.modules.iam.permissions import P
from app.modules.iam.policy import Principal
from app.modules.query.cache import get_cache
from app.modules.query.guard import GuardError, TableInfo, guard
from app.modules.query.models import QueryRun, RlsRule

log = structlog.get_logger("query")


class QueryFailed(AppError):
    status_code = 422
    code = "query_failed"


class QueryTimedOut(AppError):
    status_code = 408
    code = "query_timeout"


@dataclass
class QueryOutcome:
    query_id: str
    columns: list[dict[str, str]]
    rows: list[list[Any]]
    row_count: int
    truncated: bool
    elapsed_ms: float
    cached: bool
    executed_sql: str
    masked_columns: list[str] = field(default_factory=list)
    filtered_columns: list[str] = field(default_factory=list)


@dataclass
class _Running:
    source_id: uuid.UUID
    user_id: uuid.UUID


_running: dict[str, _Running] = {}


def _jsonable(v: Any) -> Any:
    if v is None or isinstance(v, (str, bool, int)):
        return v
    if isinstance(v, float):
        return None if math.isnan(v) or math.isinf(v) else v
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, (datetime, date, time)):
        return v.isoformat()
    if isinstance(v, (bytes, bytearray)):
        return base64.b64encode(bytes(v)).decode()
    if isinstance(v, (list, tuple)):
        return [_jsonable(x) for x in v]
    if isinstance(v, dict):
        return {str(k): _jsonable(x) for k, x in v.items()}
    return str(v)


def make_resolver(index: dict[tuple[str, str], TableInfo], default_schemas: list[str]) -> Any:
    by_name: dict[str, list[TableInfo]] = {}
    for (_, name), info in index.items():
        by_name.setdefault(name, []).append(info)

    def resolve(schema: str, name: str) -> TableInfo | None:
        if schema:
            return index.get((schema.lower(), name.lower()))
        candidates = by_name.get(name.lower(), [])
        if len(candidates) == 1:
            return candidates[0]
        for s in default_schemas:
            for c in candidates:
                if c.schema.lower() == s.lower():
                    return c
        return None

    return resolve


def _default_schemas(source: DataSource) -> list[str]:
    cfg = source.config
    schemas = [s.strip() for s in str(cfg.get("schemas", "")).split(",") if s.strip()]
    return [*schemas, str(cfg.get("database", "")), "public", "main", "default"]


async def row_filters_for(db: AsyncSession, principal: Principal, project: Project | None) -> dict[str, list[Any]]:
    """Project data scope intersected with the RLS rules matching the principal's roles."""
    filters: dict[str, list[Any]] = {k: list(v) for k, v in (project.data_scope if project else {}).items()}
    roles = set(principal.roles_by_project.get(None, ()))
    if project:
        roles |= set(principal.roles_by_project.get(project.id, ()))
    q = select(RlsRule).where(RlsRule.org_id == principal.org_id, RlsRule.enabled.is_(True))
    for rule in (await db.execute(q)).scalars():
        if rule.project_id is not None and (project is None or rule.project_id != project.id):
            continue
        if rule.role_key is not None and rule.role_key not in roles:
            continue
        if rule.column in filters:
            filters[rule.column] = [v for v in filters[rule.column] if v in rule.values]
        else:
            filters[rule.column] = list(rule.values)
    return filters


def check_sql_access(principal: Principal, source: DataSource, project: Project | None) -> None:
    """Rules of the SQL editor: sql:run in a project for its sources, or sql:run_all for any source."""
    if principal.can(P.SQL_RUN_ALL):
        return
    if project is None:
        raise PermissionDenied("Выберите проект", details={"permission": P.SQL_RUN})
    principal.require(P.SQL_RUN, project.id)
    if not source_allowed_in(source, project.id):
        raise PermissionDenied("Источник не подключён к проекту")


async def load_project(db: AsyncSession, principal: Principal, project_id: uuid.UUID | None) -> Project | None:
    if project_id is None:
        return None
    project = await db.get(Project, project_id)
    if project is None or project.org_id != principal.org_id:
        raise NotFoundError("Проект не найден")
    visible = principal.visible_project_ids()
    if visible is not None and project.id not in visible:
        raise NotFoundError("Проект не найден")
    return project


async def validate(
    db: AsyncSession, principal: Principal, source: DataSource, project: Project | None, sql: str
) -> str:
    """Runs the guard without executing: returns the SQL as it would be executed or raises ``GuardError``."""
    dialect = (await pool.get(source)).dialect
    index = await catalog_index(db, source)
    guarded = guard(
        sql,
        dialect,
        make_resolver(index, _default_schemas(source)),
        row_filters=await row_filters_for(db, principal, project),
        mask_pii=not principal.can(P.PII_VIEW, project.id if project else None),
    )
    return guarded.sql


async def execute(
    db: AsyncSession,
    principal: Principal,
    source: DataSource,
    project: Project | None,
    sql: str,
    *,
    origin: str = "sql_editor",
    limit: int | None = None,
    use_cache: bool = True,
    query_id: str | None = None,
) -> QueryOutcome:
    """Runs SQL on behalf of the principal. The caller has already checked *why* the principal may run it
    (sql:run for the editor, dashboards:view for a stored widget…); this function always applies data rules."""
    settings = get_settings()
    query_id = query_id or uuid.uuid4().hex
    connector_cls_dialect = (await pool.get(source)).dialect
    row_limit = min(limit or source.row_limit or settings.query_default_limit, settings.query_max_limit)
    run = QueryRun(
        org_id=principal.org_id,
        user_id=principal.id if principal.kind == "user" else None,
        source_id=source.id,
        project_id=project.id if project else None,
        origin=origin,
        sql=sql,
        status="error",
    )
    db.add(run)
    try:
        index = await catalog_index(db, source)
        filters = await row_filters_for(db, principal, project)
        guarded = guard(
            sql,
            connector_cls_dialect,
            make_resolver(index, _default_schemas(source)),
            row_filters=filters,
            mask_pii=not principal.can(P.PII_VIEW, project.id if project else None),
            limit=row_limit + 1,
        )
    except GuardError as exc:
        run.status, run.error = "denied", exc.message
        await record(
            db,
            "query.rejected",
            principal=principal,
            resource_type="data_source",
            resource_id=source.id,
            project_id=run.project_id,
            outcome="denied",
            sql=sql,
            details={"reason": exc.message},
        )
        await db.commit()
        raise
    run.executed_sql = guarded.sql
    cache_key = f"{source.id}:{hashlib.sha256(guarded.sql.encode()).hexdigest()}"
    cache = get_cache()
    if use_cache and (hit := await cache.get(cache_key)):
        outcome = QueryOutcome(
            query_id=query_id,
            cached=True,
            executed_sql=guarded.sql,
            masked_columns=guarded.masked,
            filtered_columns=guarded.filtered,
            **hit,
        )
        run.status, run.row_count, run.elapsed_ms, run.cached = "ok", outcome.row_count, 0.0, True
        await record(
            db,
            "query.run",
            principal=principal,
            resource_type="data_source",
            resource_id=source.id,
            project_id=run.project_id,
            sql=guarded.sql,
            row_count=outcome.row_count,
            details={"origin": origin, "cached": True},
        )
        await db.commit()
        return outcome

    connector = await pool.get(source)
    _running[query_id] = _Running(source.id, principal.id)
    status = "error"
    error = ""
    try:
        async with pool.semaphore(source.id):
            result = await connector.execute(guarded.sql, None, row_limit, source.timeout_s, query_id)
        status = "ok"
    except QueryTimeout as exc:
        status, error = "timeout", str(exc)
        raise QueryTimedOut(error) from exc
    except QueryCancelled as exc:
        status, error = "cancelled", str(exc)
        raise QueryFailed(error) from exc
    except ConnectorError as exc:
        error = str(exc)
        raise QueryFailed(error) from exc
    finally:
        _running.pop(query_id, None)
        run.status, run.error = status, error
        if status != "ok":
            await record(
                db,
                "query.run",
                principal=principal,
                resource_type="data_source",
                resource_id=source.id,
                project_id=run.project_id,
                outcome="error",
                sql=guarded.sql,
                details={"origin": origin, "error": error[:500], "status": status},
            )
            await db.commit()

    payload: dict[str, Any] = {
        "columns": [{"name": c.name, "type": c.type} for c in result.columns],
        "rows": [[_jsonable(v) for v in row] for row in result.rows],
        "row_count": result.row_count,
        "truncated": result.truncated,
        "elapsed_ms": result.elapsed_ms,
    }
    await cache.set(cache_key, payload, source.cache_ttl_s)
    run.row_count, run.elapsed_ms = result.row_count, result.elapsed_ms
    await record(
        db,
        "query.run",
        principal=principal,
        resource_type="data_source",
        resource_id=source.id,
        project_id=run.project_id,
        sql=guarded.sql,
        row_count=result.row_count,
        details={"origin": origin, "elapsed_ms": result.elapsed_ms},
    )
    await db.commit()
    return QueryOutcome(
        query_id=query_id,
        cached=False,
        executed_sql=guarded.sql,
        masked_columns=guarded.masked,
        filtered_columns=guarded.filtered,
        **payload,
    )


async def cancel(principal: Principal, query_id: str) -> bool:
    item = _running.get(query_id)
    if item is None:
        return False
    if item.user_id != principal.id and not principal.can(P.ADMIN_AUDIT):
        raise PermissionDenied("Можно отменить только свой запрос")
    connector = pool._items.get(item.source_id)
    if connector:
        await asyncio.shield(connector[1].cancel(query_id))
    return True
