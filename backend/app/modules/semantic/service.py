"""Semantic layer use-cases: domain pack install, metric versioning, running metric queries via Query Service."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFoundError, PermissionDenied, ValidationFailed
from app.modules.connectors.models import CatalogTable, DataSource
from app.modules.connectors.service import pool, source_allowed_in
from app.modules.iam.models import Project
from app.modules.iam.permissions import P
from app.modules.iam.policy import Principal
from app.modules.query import service as query_service
from app.modules.semantic.compiler import (
    DimensionDef,
    Filter,
    Grain,
    MetricDef,
    SemanticSpec,
    compile_spec,
    merge_results,
    validate_metric,
)
from app.modules.semantic.models import Dimension, Metric, MetricVersion

PACKS_DIR = Path(__file__).resolve().parents[3] / "starter_kit"
DEFINITION_FIELDS = (
    "name",
    "description",
    "table",
    "time_column",
    "expression",
    "filters",
    "maturity_days",
    "default_dimensions",
    "format",
    "owner",
    "tags",
    "source_id",
)


def metric_def(m: Metric) -> MetricDef:
    return MetricDef(
        m.key, m.table, m.time_column, m.expression, m.filters or "", m.maturity_days, tuple(m.default_dimensions or ())
    )


def snapshot(m: Metric) -> dict[str, Any]:
    return {f: (str(getattr(m, f)) if f == "source_id" and getattr(m, f) else getattr(m, f)) for f in DEFINITION_FIELDS}


async def add_version(db: AsyncSession, m: Metric, author: str) -> None:
    db.add(MetricVersion(metric_id=m.id, version=m.version, definition=snapshot(m), author=author))


def available_packs() -> list[str]:
    return sorted(p.name for p in PACKS_DIR.iterdir() if (p / "metrics.yaml").exists()) if PACKS_DIR.exists() else []


async def install_pack(db: AsyncSession, org_id: uuid.UUID, pack: str, author: str = "system") -> dict[str, int]:
    path = PACKS_DIR / pack / "metrics.yaml"
    if pack not in available_packs():
        raise NotFoundError(f"Доменный пакет {pack} не найден")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    dims = {d.key: d for d in (await db.execute(select(Dimension).where(Dimension.org_id == org_id))).scalars()}
    added_d = 0
    for d in data.get("dimensions", []):
        if d["key"] not in dims:
            db.add(
                Dimension(
                    org_id=org_id,
                    key=d["key"],
                    name=d["name"],
                    column=d["column"],
                    description=d.get("description", ""),
                )
            )
            added_d += 1
    metrics = {m.key: m for m in (await db.execute(select(Metric).where(Metric.org_id == org_id))).scalars()}
    added_m = 0
    for raw in data.get("metrics", []):
        if raw["key"] in metrics:
            continue  # never overwrite customer edits
        m = Metric(
            org_id=org_id,
            key=raw["key"],
            name=raw["name"],
            description=raw.get("description", ""),
            table=raw["table"],
            time_column=raw["time_column"],
            expression=raw["expression"].strip(),
            filters=raw.get("filters", ""),
            maturity_days=raw.get("maturity_days", 0),
            default_dimensions=raw.get("default_dimensions", []),
            format=raw.get("format", "number"),
            owner="starter-kit",
            tags=raw.get("tags", [pack]),
            pack=pack,
            version=1,
        )
        validate_metric(metric_def(m))
        db.add(m)
        await db.flush()
        await add_version(db, m, author)
        added_m += 1
    await db.flush()
    return {"metrics": added_m, "dimensions": added_d}


# ------------------------------------------------------------------ querying
@dataclass
class Cohort:
    label: str
    filters: list[Filter] = field(default_factory=list)


@dataclass
class SemanticRequest:
    metrics: list[str]
    dimensions: list[str] = field(default_factory=list)
    grain: Grain = "none"
    date_from: date | None = None
    date_to: date | None = None
    filters: list[Filter] = field(default_factory=list)
    cohorts: list[Cohort] = field(default_factory=list)
    limit: int = 5000


@dataclass
class SemanticResult:
    columns: list[dict[str, str]]
    rows: list[list[Any]]
    sql: list[str]
    cached: bool


def check_semantic_access(principal: Principal, project: Project | None) -> None:
    if project is None:
        if not principal.can(P.PORTFOLIO_VIEW):
            raise PermissionDenied("Портфельные запросы доступны руководству", details={"permission": P.PORTFOLIO_VIEW})
        return
    if not (
        principal.can(P.SEMANTIC_VIEW, project.id)
        or principal.can(P.DASHBOARDS_VIEW, project.id)
        or principal.can(P.DASHBOARDS_VIEW_SHARED, project.id)
    ):
        raise PermissionDenied("Нет доступа к метрикам проекта", details={"permission": P.SEMANTIC_VIEW})


async def _source_for_table(
    db: AsyncSession, principal: Principal, project: Project | None, table: str, fixed: uuid.UUID | None
) -> tuple[DataSource, set[str]]:
    q = (
        select(DataSource, CatalogTable)
        .join(CatalogTable, CatalogTable.source_id == DataSource.id)
        .where(
            DataSource.org_id == principal.org_id,
            func.lower(CatalogTable.name) == table.lower(),
            CatalogTable.present.is_(True),
        )
        .order_by(DataSource.is_demo, DataSource.created_at)
    )
    if fixed:
        q = q.where(DataSource.id == fixed)
    for source, tbl in (await db.execute(q)).all():
        if project is None or source_allowed_in(source, project.id):
            return source, {c.name for c in tbl.columns if c.present}
    raise ValidationFailed(f"Таблица {table} не найдена ни в одном источнике проекта")


async def run(
    db: AsyncSession, principal: Principal, project: Project | None, req: SemanticRequest, origin: str = "semantic"
) -> SemanticResult:
    check_semantic_access(principal, project)
    rows_m = (
        await db.execute(select(Metric).where(Metric.org_id == principal.org_id, Metric.key.in_(req.metrics)))
    ).scalars()
    by_key = {m.key: m for m in rows_m}
    missing = [k for k in req.metrics if k not in by_key]
    if missing:
        raise ValidationFailed("Неизвестные метрики", details={"metrics": missing})
    dims_all = {
        d.key: d for d in (await db.execute(select(Dimension).where(Dimension.org_id == principal.org_id))).scalars()
    }
    dims = []
    for k in req.dimensions:
        if k not in dims_all:
            raise ValidationFailed(f"Неизвестное измерение {k}")
        dims.append(DimensionDef(k, dims_all[k].column))
    filters = [Filter(f.dimension, f.op, f.values) for f in req.filters]
    metrics = [by_key[k] for k in req.metrics]

    cohorts = req.cohorts or [Cohort("")]
    all_columns: list[str] = []
    all_rows: list[list[Any]] = []
    sqls: list[str] = []
    cached = True
    for cohort in cohorts:
        spec = SemanticSpec(
            [metric_def(m) for m in metrics],
            dims,
            req.grain,
            req.date_from,
            req.date_to,
            [*filters, *cohort.filters],
            req.limit,
        )
        results = []
        # one query per (source, table, filter group)
        tables = {m.table: m.source_id for m in metrics}
        resolved = {t: await _source_for_table(db, principal, project, t, sid) for t, sid in tables.items()}
        dialect_by_table = {t: (await pool.get(src)).dialect for t, (src, _) in resolved.items()}
        for group in _compile_per_table(spec, resolved, dialect_by_table):
            source = resolved[group.table][0]
            out = await query_service.execute(db, principal, source, project, group.sql, origin=origin, limit=req.limit)
            cached = cached and out.cached
            sqls.append(out.executed_sql)
            results.append((group, [c["name"] for c in out.columns], out.rows))
        columns, rows = merge_results(spec, results)
        if req.cohorts:
            columns = ["cohort", *columns]
            rows = [[cohort.label, *r] for r in rows]
        all_columns = columns
        all_rows.extend(rows)

    roles = {"cohort": "dimension", "period": "period", **{d.key: "dimension" for d in dims}}
    fmt = {m.key: m.format for m in metrics}
    names = (
        {m.key: m.name for m in metrics}
        | {d.key: dims_all[d.key].name for d in dims}
        | {"period": "Период", "cohort": "Когорта"}
    )
    col_meta = [
        {"key": c, "name": names.get(c, c), "role": roles.get(c, "metric"), "format": fmt.get(c, "")}
        for c in all_columns
    ]
    return SemanticResult(columns=col_meta, rows=all_rows, sql=sqls, cached=cached)


def _compile_per_table(
    spec: SemanticSpec, resolved: dict[str, tuple[DataSource, set[str]]], dialects: dict[str, str]
) -> list[Any]:
    out = []
    for table in {m.table for m in spec.metrics}:
        sub = SemanticSpec(
            [m for m in spec.metrics if m.table == table],
            spec.dimensions,
            spec.grain,
            spec.date_from,
            spec.date_to,
            spec.filters,
            spec.limit,
        )
        out.extend(compile_spec(sub, dialects[table], {table: resolved[table][1]}))
    return out


async def dimension_values(
    db: AsyncSession, principal: Principal, project: Project | None, key: str, limit: int = 200
) -> list[Any]:
    """Distinct values of a dimension for filter pickers (subject to RLS like any other query)."""
    check_semantic_access(principal, project)
    dim = (
        await db.execute(select(Dimension).where(Dimension.org_id == principal.org_id, Dimension.key == key))
    ).scalar_one_or_none()
    if dim is None:
        raise NotFoundError("Измерение не найдено")
    q = (
        select(DataSource, CatalogTable)
        .join(CatalogTable, CatalogTable.source_id == DataSource.id)
        .where(DataSource.org_id == principal.org_id, CatalogTable.present.is_(True))
        .order_by(CatalogTable.row_count.asc().nulls_last())
    )
    for source, table in (await db.execute(q)).all():
        if project is not None and not source_allowed_in(source, project.id):
            continue
        if any(c.name == dim.column and c.present and not c.is_pii for c in table.columns):
            col = f'"{dim.column}"'
            sql = f"SELECT DISTINCT {col} AS v FROM {table.name} WHERE {col} IS NOT NULL ORDER BY 1"
            out = await query_service.execute(db, principal, source, project, sql, origin="semantic", limit=limit)
            return [r[0] for r in out.rows]
    return []
