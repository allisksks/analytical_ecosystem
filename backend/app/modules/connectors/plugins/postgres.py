"""PostgreSQL and Greenplum (live mode, asyncpg)."""

from __future__ import annotations

import asyncio
import ssl
import time
from typing import Any, ClassVar

import asyncpg

from app.modules.connectors.base import (
    ColumnMeta,
    Connector,
    ConnectorError,
    QueryCancelled,
    QueryResult,
    QueryTimeout,
    ResultColumn,
    TableMeta,
    schema_prop,
)

CATALOG_SQL = """
SELECT c.table_schema, c.table_name, t.table_type, c.column_name, c.data_type, c.is_nullable,
       coalesce(col_description(pc.oid, c.ordinal_position), '') AS col_comment,
       coalesce(obj_description(pc.oid, 'pg_class'), '') AS tbl_comment,
       greatest(pc.reltuples, 0)::bigint AS row_estimate
FROM information_schema.columns c
JOIN information_schema.tables t ON t.table_schema = c.table_schema AND t.table_name = c.table_name
JOIN pg_namespace pn ON pn.nspname = c.table_schema
JOIN pg_class pc ON pc.relname = c.table_name AND pc.relnamespace = pn.oid
WHERE c.table_schema = ANY($1::text[])
ORDER BY c.table_schema, c.table_name, c.ordinal_position
"""


class PostgresConnector(Connector):
    type = "postgres"
    title = "PostgreSQL / Greenplum"
    dialect = "postgres"
    secret_fields = ("password",)
    config_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "required": ["host", "database", "user"],
        "properties": {
            "host": schema_prop("Хост"),
            "port": schema_prop("Порт", type_="integer", default=5432),
            "database": schema_prop("База данных"),
            "user": schema_prop("Пользователь", description="Рекомендуется учётная запись только на чтение"),
            "password": schema_prop("Пароль", secret=True),
            "schemas": schema_prop("Схемы через запятую", default="public"),
            "sslmode": schema_prop("TLS", enum=["disable", "prefer", "require", "verify-full"], default="prefer"),
        },
    }

    def __init__(self, config: dict[str, Any], secrets: dict[str, Any]) -> None:
        super().__init__(config, secrets)
        self._pool: asyncpg.Pool | None = None
        self._pids: dict[str, int] = {}

    def _ssl(self) -> Any:
        mode = self.config.get("sslmode", "prefer")
        if mode == "disable":
            return False
        if mode == "verify-full":
            return ssl.create_default_context()
        return mode

    async def _get_pool(self) -> asyncpg.Pool:
        if self._pool is None:
            try:
                self._pool = await asyncpg.create_pool(
                    host=self.config["host"],
                    port=int(self.config.get("port", 5432)),
                    database=self.config["database"],
                    user=self.config["user"],
                    password=self.secrets.get("password"),
                    ssl=self._ssl(),
                    min_size=0,
                    max_size=int(self.config.get("pool_size", 4)),
                    timeout=10,
                    server_settings={"application_name": "analytics-platform"},
                )
            except (OSError, asyncpg.PostgresError) as exc:
                raise ConnectorError(str(exc)) from exc
        return self._pool

    async def _ping(self) -> str:
        pool = await self._get_pool()
        version = await pool.fetchval("SELECT version()")
        return str(version).split(",")[0]

    def _schemas(self) -> list[str]:
        return [s.strip() for s in str(self.config.get("schemas", "public")).split(",") if s.strip()]

    async def list_catalog(self) -> list[TableMeta]:
        pool = await self._get_pool()
        rows = await pool.fetch(CATALOG_SQL, self._schemas())
        tables: dict[tuple[str, str], TableMeta] = {}
        for r in rows:
            key = (r["table_schema"], r["table_name"])
            t = tables.get(key)
            if t is None:
                t = TableMeta(
                    schema=key[0],
                    name=key[1],
                    kind="view" if r["table_type"] == "VIEW" else "table",
                    row_count=int(r["row_estimate"]),
                    comment=r["tbl_comment"],
                )
                tables[key] = t
            t.columns.append(ColumnMeta(r["column_name"], r["data_type"], r["is_nullable"] == "YES", r["col_comment"]))
        return list(tables.values())

    async def execute(
        self, sql: str, params: dict[str, Any] | None, limit: int, timeout_s: int, query_id: str
    ) -> QueryResult:
        pool = await self._get_pool()
        start = time.perf_counter()
        async with pool.acquire() as conn:
            self._pids[query_id] = conn.get_server_pid()
            try:
                async with conn.transaction(readonly=True):
                    await conn.execute(f"SET LOCAL statement_timeout = {int(timeout_s) * 1000}")
                    stmt = await conn.prepare(sql)
                    rows = await _fetch_limited(stmt, limit)
                    attrs = stmt.get_attributes()
            except asyncpg.QueryCanceledError as exc:
                if "statement timeout" in str(exc):
                    raise QueryTimeout(f"Превышено время выполнения ({timeout_s} с)") from exc
                raise QueryCancelled("Запрос отменён") from exc
            except asyncpg.PostgresError as exc:
                raise ConnectorError(str(exc)) from exc
            finally:
                self._pids.pop(query_id, None)
        return QueryResult(
            columns=[ResultColumn(a.name, a.type.name) for a in attrs],
            rows=[list(r.values()) for r in rows[:limit]],
            truncated=len(rows) > limit,
            elapsed_ms=round((time.perf_counter() - start) * 1000, 1),
        )

    async def cancel(self, query_id: str) -> None:
        pid = self._pids.get(query_id)
        if pid and self._pool is not None:
            await self._pool.execute("SELECT pg_cancel_backend($1)", pid)

    async def close(self) -> None:
        if self._pool is not None:
            await asyncio.wait_for(self._pool.close(), 5)
            self._pool = None


async def _fetch_limited(stmt: asyncpg.prepared_stmt.PreparedStatement, limit: int) -> list[asyncpg.Record]:
    """Streams with a cursor and stops after ``limit + 1`` rows (never materialises a huge result)."""
    out: list[asyncpg.Record] = []
    async for rec in stmt.cursor(prefetch=min(limit + 1, 5000)):
        out.append(rec)
        if len(out) > limit:
            break
    return out
