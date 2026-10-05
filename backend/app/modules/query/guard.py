"""SQL guard: the single gate every query (manual, dashboard, semantic layer, AI) passes before a source.

1. parse with sqlglot in the source dialect; exactly one statement, and it must be a read-only query;
2. forbid table functions (file/url/s3/read_csv…), SELECT INTO, locks and dangerous scalar functions;
3. every table must exist in the platform catalog of the source (fail closed: no system tables);
4. row-level security: tables having a restricted column are replaced by a filtered subquery;
5. PII masking: personal-data columns are replaced by their MD5 hash for users without ``pii:view``
   (distinct counts and joins keep working, raw values never leave the source);
6. a LIMIT is enforced.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Any

import sqlglot
from sqlglot import exp
from sqlglot.errors import ParseError

from app.core.errors import ValidationFailed


class GuardError(ValidationFailed):
    code = "query_rejected"


FORBIDDEN_FUNCTIONS = frozenset(
    {
        # PostgreSQL: file access, arbitrary SQL execution bypassing rewriting, DoS, server control
        "pg_read_file",
        "pg_read_binary_file",
        "pg_ls_dir",
        "pg_stat_file",
        "pg_sleep",
        "pg_sleep_for",
        "pg_sleep_until",
        "pg_terminate_backend",
        "pg_cancel_backend",
        "pg_reload_conf",
        "set_config",
        "lo_import",
        "lo_export",
        "lo_get",
        "lo_put",
        "dblink",
        "dblink_exec",
        "query_to_xml",
        "query_to_json",
        "table_to_xml",
        "database_to_xml",
        "schema_to_xml",
        "cursor_to_xml",
        "query_to_xml_and_xmlschema",
        # MySQL
        "load_file",
        "sleep",
        "benchmark",
        "get_lock",
        "release_lock",
        "sys_exec",
        "sys_eval",
        # ClickHouse
        "sleepeachrow",
        "dictget",
        "dictgetordefault",
        "dictgetornull",
        "dictgethierarchy",
        "joinget",
        "file",
        "url",
        "s3",
        "remote",
        "remotesecure",
        "input",
        "executable",
        # DuckDB
        "getenv",
        "read_text",
        "read_blob",
        "read_csv",
        "read_csv_auto",
        "read_parquet",
        "read_json",
        "read_json_auto",
        "read_xlsx",
        "glob",
        "sniff_csv",
        "query",
        "query_table",
    }
)

FORBIDDEN_NODES: tuple[type[exp.Expression], ...] = (
    exp.Insert,
    exp.Update,
    exp.Delete,
    exp.Merge,
    exp.Create,
    exp.Drop,
    exp.Alter,
    exp.Command,
    exp.Into,
    exp.Lock,
    exp.Set,
    exp.Pragma,
    exp.Use,
    exp.Transaction,
    exp.Commit,
    exp.Rollback,
    exp.Copy,
    exp.LoadData,
    exp.TruncateTable,
    exp.Grant,
)


@dataclass(frozen=True)
class TableInfo:
    schema: str
    name: str
    columns: tuple[str, ...]
    pii: frozenset[str] = frozenset()


@dataclass
class GuardResult:
    sql: str
    tables: list[TableInfo] = field(default_factory=list)
    filtered: list[str] = field(default_factory=list)
    masked: list[str] = field(default_factory=list)


Resolver = Callable[[str, str], TableInfo | None]


def _function_name(node: exp.Func) -> str:
    if isinstance(node, exp.Anonymous):
        return str(node.name).lower()
    return node.sql_name().lower()


def parse_read_only(sql: str, dialect: str) -> exp.Query:
    if not sql or not sql.strip():
        raise GuardError("Пустой запрос")
    try:
        statements = [s for s in sqlglot.parse(sql, read=dialect) if s is not None]
    except ParseError as exc:
        errors = exc.errors[:1]
        hint = errors[0].get("description", "") if errors else str(exc)
        raise GuardError(f"Не удалось разобрать SQL: {hint}") from exc
    if len(statements) != 1:
        raise GuardError("Разрешён ровно один запрос")
    stmt = statements[0]
    if not isinstance(stmt, exp.Query):
        raise GuardError("Разрешены только запросы на чтение (SELECT)")
    for node in stmt.walk():
        if isinstance(node, FORBIDDEN_NODES):
            raise GuardError(f"Конструкция запрещена: {type(node).__name__.upper()}")
        if isinstance(node, exp.Func) and _function_name(node) in FORBIDDEN_FUNCTIONS:
            raise GuardError(f"Функция запрещена: {_function_name(node)}")
        if isinstance(node, exp.Table) and not isinstance(node.this, exp.Identifier):
            raise GuardError("Табличные функции запрещены — используйте таблицы из каталога")
    return stmt


def _cte_names(stmt: exp.Query) -> set[str]:
    return {cte.alias_or_name.lower() for cte in stmt.find_all(exp.CTE)}


def _in_filter(column: str, values: Iterable[Any]) -> exp.Expression:
    vals = list(values)
    if not vals:
        return exp.false()
    return exp.column(column, quoted=True).isin(*[exp.convert(v) for v in vals])


def _enforce_limit(stmt: exp.Query, limit: int) -> exp.Query:
    current = stmt.args.get("limit")
    if current is None:
        return stmt.limit(limit, copy=False)
    expr = current.expression if isinstance(current, exp.Limit) else None
    if isinstance(expr, exp.Literal) and expr.is_int and int(expr.this) <= limit:
        return stmt
    return stmt.limit(limit, copy=False)


def guard(
    sql: str,
    dialect: str,
    resolve: Resolver,
    *,
    row_filters: dict[str, list[Any]] | None = None,
    mask_pii: bool = True,
    limit: int | None = None,
) -> GuardResult:
    stmt = parse_read_only(sql, dialect)
    ctes = _cte_names(stmt)
    result = GuardResult(sql="")
    filters = row_filters or {}
    for table in list(stmt.find_all(exp.Table)):
        if not table.db and table.name.lower() in ctes:
            continue
        info = resolve(table.db, table.name)
        if info is None:
            ref = f"{table.db}.{table.name}" if table.db else table.name
            raise GuardError(f"Таблица {ref} не найдена в каталоге источника (обновите каталог)")
        result.tables.append(info)
        cols = {c.lower(): c for c in info.columns}
        applicable = {cols[c.lower()]: v for c, v in filters.items() if c.lower() in cols}
        masked = sorted(info.pii) if mask_pii else []
        if not applicable and not masked:
            continue
        source = table.copy()
        source.set("alias", None)
        if masked:
            projection: list[exp.Expr] = [
                exp.alias_(exp.MD5(this=exp.cast(exp.column(c, quoted=True), "text")), c, quoted=True)
                if c in info.pii
                else exp.column(c, quoted=True)
                for c in info.columns
            ]
        else:
            projection = [exp.Star()]
        sub = exp.select(*projection).from_(source)
        for col, values in applicable.items():
            sub = sub.where(_in_filter(col, values), copy=False)
        alias = table.alias or table.name
        table.replace(exp.Subquery(this=sub, alias=exp.TableAlias(this=exp.to_identifier(alias))))
        result.filtered.extend(f"{info.name}.{c}" for c in applicable)
        result.masked.extend(f"{info.name}.{c}" for c in masked)
    if limit is not None:
        stmt = _enforce_limit(stmt, limit)
    result.sql = stmt.sql(dialect=dialect)
    return result
