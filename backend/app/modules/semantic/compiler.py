"""Compiles semantic queries (metrics x dimensions x time grain x filters) into SQL of any supported dialect.

Metric expressions are written once in a neutral (PostgreSQL-like) dialect and transpiled by sqlglot,
so the same definition works on ClickHouse, PostgreSQL, MySQL and DuckDB. Metrics living in the same
table with the same filters are computed in one query; groups are merged by (period, dimensions).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Literal

import sqlglot
from sqlglot import exp
from sqlglot.errors import ParseError

from app.core.errors import ValidationFailed

NEUTRAL = "postgres"
Grain = Literal["none", "day", "week", "month"]
FilterOp = Literal["in", "not_in", "gte", "lte", "eq"]


@dataclass(frozen=True)
class MetricDef:
    key: str
    table: str
    time_column: str
    expression: str
    filters: str = ""
    maturity_days: int = 0
    default_dimensions: tuple[str, ...] = ()


@dataclass(frozen=True)
class DimensionDef:
    key: str
    column: str


@dataclass(frozen=True)
class Filter:
    dimension: str
    op: FilterOp
    values: tuple[Any, ...]


@dataclass
class CompiledGroup:
    table: str
    metrics: list[str]
    sql: str


@dataclass
class SemanticSpec:
    metrics: list[MetricDef]
    dimensions: list[DimensionDef] = field(default_factory=list)
    grain: Grain = "none"
    date_from: date | None = None
    date_to: date | None = None
    filters: list[Filter] = field(default_factory=list)
    limit: int = 5000


def parse_expression(sql: str, what: str) -> exp.Expr:
    try:
        parsed = sqlglot.parse_one(sql, read=NEUTRAL)
    except ParseError as exc:
        raise ValidationFailed(
            f"Ошибка в {what}: {exc.errors[0].get('description', '') if exc.errors else exc}"
        ) from exc
    if parsed is None:
        raise ValidationFailed(f"Пустое выражение: {what}")
    return parsed


def validate_metric(m: MetricDef) -> None:
    expr = parse_expression(m.expression, f"формуле метрики {m.key}")
    if not any(isinstance(n, exp.AggFunc) for n in expr.walk()):
        raise ValidationFailed(f"Формула метрики {m.key} должна содержать агрегат (SUM, COUNT, AVG…)")
    if m.filters:
        parse_expression(m.filters, f"фильтре метрики {m.key}")


def _filter_expr(column: str, f: Filter) -> exp.Expr:
    col = exp.column(column, quoted=True)
    vals = [exp.convert(v) for v in f.values]
    if f.op == "in":
        return col.isin(*vals) if vals else exp.false()
    if f.op == "not_in":
        return exp.not_(col.isin(*vals)) if vals else exp.true()
    if not vals:
        raise ValidationFailed(f"Для фильтра {f.dimension} нужно значение")
    if f.op == "eq":
        return exp.EQ(this=col, expression=vals[0])
    if f.op == "gte":
        return exp.GTE(this=col, expression=vals[0])
    return exp.LTE(this=col, expression=vals[0])


def _date_literal(d: date) -> exp.Expr:
    return exp.cast(exp.Literal.string(d.isoformat()), "date")


def _group_key(m: MetricDef) -> tuple[str, str, str, int]:
    return (m.table, m.time_column, m.filters.strip(), m.maturity_days)


def compile_spec(
    spec: SemanticSpec, dialect: str, table_columns: dict[str, set[str]] | None = None
) -> list[CompiledGroup]:
    if not spec.metrics:
        raise ValidationFailed("Выберите хотя бы одну метрику")
    groups: dict[tuple[str, str, str, int], list[MetricDef]] = {}
    for m in spec.metrics:
        validate_metric(m)
        groups.setdefault(_group_key(m), []).append(m)

    dims_by_key = {d.key: d for d in spec.dimensions}
    out: list[CompiledGroup] = []
    for (table, time_column, metric_filter, maturity), metrics in groups.items():
        cols = (table_columns or {}).get(table)
        for d in spec.dimensions:
            if cols is not None and d.column not in cols:
                raise ValidationFailed(f"Измерение «{d.key}» недоступно для метрик из таблицы {table}")
        time_col = exp.column(time_column, quoted=True)
        select: list[exp.Expr] = []
        group_by: list[exp.Expr] = []
        partition: list[exp.Expr] = []
        if spec.grain != "none":
            period = exp.DateTrunc(this=time_col.copy(), unit=exp.Literal.string(spec.grain))  # type: ignore[no-untyped-call]
            select.append(exp.alias_(exp.cast(period, "date"), "period", quoted=True))
            group_by.append(exp.cast(period.copy(), "date"))
            partition.append(exp.cast(period.copy(), "date"))
        curve_dims = {k for m in metrics for k in m.default_dimensions}
        for d in spec.dimensions:
            c = exp.column(d.column, quoted=True)
            select.append(exp.alias_(c, d.key, quoted=True))
            group_by.append(c.copy())
            if d.key not in curve_dims:
                partition.append(c.copy())
        for m in metrics:
            expr = parse_expression(m.expression, f"формуле метрики {m.key}")
            for w in expr.find_all(exp.Window):
                w.set("partition_by", [p.copy() for p in partition] or None)
            select.append(exp.alias_(expr, m.key, quoted=True))

        query = exp.select(*select).from_(exp.to_table(table))
        conds: list[exp.Expr] = []
        if spec.date_from:
            conds.append(exp.GTE(this=time_col.copy(), expression=_date_literal(spec.date_from)))
        if spec.date_to:
            conds.append(exp.LTE(this=time_col.copy(), expression=_date_literal(spec.date_to)))
        if maturity:
            conds.append(
                exp.LTE(
                    this=time_col.copy(),
                    expression=parse_expression(f"CURRENT_DATE - INTERVAL '{int(maturity)} day'", "maturity"),
                )
            )
        if metric_filter:
            conds.append(exp.paren(parse_expression(metric_filter, "фильтре метрики")))
        for f in spec.filters:
            d = dims_by_key.get(f.dimension) or DimensionDef(f.dimension, f.dimension)
            if cols is not None and d.column not in cols:
                continue  # filter on a dimension this table does not have: not applicable
            conds.append(_filter_expr(d.column, f))
        for cond in conds:
            query = query.where(cond, copy=False)
        if group_by:
            query = query.group_by(*group_by, copy=False)
            query = query.order_by(*[g.copy() for g in group_by], copy=False)
        query = query.limit(spec.limit, copy=False)
        out.append(CompiledGroup(table=table, metrics=[m.key for m in metrics], sql=query.sql(dialect=dialect)))
    return out


def merge_results(
    spec: SemanticSpec, results: Sequence[tuple[CompiledGroup, list[str], list[list[Any]]]]
) -> tuple[list[str], list[list[Any]]]:
    """Joins per-table results on (period, dimensions) — a full outer join done in Python."""
    key_cols = (["period"] if spec.grain != "none" else []) + [d.key for d in spec.dimensions]
    metric_cols = [m.key for m in spec.metrics]
    merged: dict[tuple[Any, ...], dict[str, Any]] = {}
    for _group, columns, rows in results:
        idx = {c: i for i, c in enumerate(columns)}
        for row in rows:
            key = tuple(row[idx[k]] for k in key_cols)
            target = merged.setdefault(key, {})
            for mk in _group.metrics:
                target[mk] = row[idx[mk]]
    ordered = sorted(merged.items(), key=lambda kv: tuple(_sort_key(v) for v in kv[0]))
    out_rows = [[*key, *(vals.get(m) for m in metric_cols)] for key, vals in ordered]
    return key_cols + metric_cols, out_rows


def _sort_key(v: Any) -> tuple[int, Any]:
    if v is None:
        return (2, "")
    if isinstance(v, (int, float)):
        return (0, v)
    return (1, str(v))
