"""MySQL and MariaDB (live mode, asyncmy)."""

from __future__ import annotations

import asyncio
import ssl
import time
from typing import Any, ClassVar

import asyncmy
from asyncmy.errors import MySQLError

from app.modules.connectors.base import (
    ColumnMeta,
    Connector,
    ConnectorError,
    QueryResult,
    QueryTimeout,
    ResultColumn,
    TableMeta,
    schema_prop,
)

CATALOG_SQL = """
SELECT c.TABLE_SCHEMA, c.TABLE_NAME, t.TABLE_TYPE, c.COLUMN_NAME, c.COLUMN_TYPE, c.IS_NULLABLE, c.COLUMN_COMMENT,
       t.TABLE_COMMENT, t.TABLE_ROWS, t.UPDATE_TIME
FROM information_schema.COLUMNS c
JOIN information_schema.TABLES t ON t.TABLE_SCHEMA = c.TABLE_SCHEMA AND t.TABLE_NAME = c.TABLE_NAME
WHERE c.TABLE_SCHEMA = %s
ORDER BY c.TABLE_NAME, c.ORDINAL_POSITION
"""


class MySQLConnector(Connector):
    type = "mysql"
    title = "MySQL / MariaDB"
    dialect = "mysql"
    secret_fields = ("password",)
    config_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "required": ["host", "database", "user"],
        "properties": {
            "host": schema_prop("Хост"),
            "port": schema_prop("Порт", type_="integer", default=3306),
            "database": schema_prop("База данных"),
            "user": schema_prop("Пользователь", description="Рекомендуется учётная запись только на чтение"),
            "password": schema_prop("Пароль", secret=True),
            "ssl": schema_prop("TLS", type_="boolean", default=False),
        },
    }

    def __init__(self, config: dict[str, Any], secrets: dict[str, Any]) -> None:
        super().__init__(config, secrets)
        self._pool: Any = None
        self._threads: dict[str, int] = {}

    async def _get_pool(self) -> Any:
        if self._pool is None:
            try:
                self._pool = await asyncmy.create_pool(
                    host=self.config["host"],
                    port=int(self.config.get("port", 3306)),
                    db=self.config["database"],
                    user=self.config["user"],
                    password=self.secrets.get("password", ""),
                    ssl=ssl.create_default_context() if self.config.get("ssl") else None,
                    minsize=0,
                    maxsize=4,
                    connect_timeout=10,
                    autocommit=True,
                )
            except (OSError, MySQLError) as exc:
                raise ConnectorError(str(exc)) from exc
        return self._pool

    async def _ping(self) -> str:
        pool = await self._get_pool()
        async with pool.acquire() as conn, conn.cursor() as cur:
            await cur.execute("SELECT VERSION()")
            row = await cur.fetchone()
            return f"MySQL {row[0]}"

    async def list_catalog(self) -> list[TableMeta]:
        pool = await self._get_pool()
        async with pool.acquire() as conn, conn.cursor() as cur:
            await cur.execute(CATALOG_SQL, (self.config["database"],))
            rows = await cur.fetchall()
        tables: dict[str, TableMeta] = {}
        for schema, name, ttype, col, ctype, nullable, ccomment, tcomment, trows, updated in rows:
            t = tables.get(name)
            if t is None:
                t = TableMeta(schema, name, "view" if ttype == "VIEW" else "table", [], trows, updated, tcomment or "")
                tables[name] = t
            t.columns.append(ColumnMeta(col, ctype, nullable == "YES", ccomment or ""))
        return list(tables.values())

    async def execute(
        self, sql: str, params: dict[str, Any] | None, limit: int, timeout_s: int, query_id: str
    ) -> QueryResult:
        pool = await self._get_pool()
        start = time.perf_counter()
        async with pool.acquire() as conn, conn.cursor() as cur:
            try:
                await cur.execute("SELECT CONNECTION_ID()")
                self._threads[query_id] = (await cur.fetchone())[0]
                await cur.execute(f"SET SESSION max_execution_time = {int(timeout_s) * 1000}")
                await cur.execute("START TRANSACTION READ ONLY")
                await cur.execute(sql)
                rows = await cur.fetchmany(limit + 1)
                desc = cur.description or []
                await cur.execute("ROLLBACK")
            except MySQLError as exc:
                if "maximum statement execution time" in str(exc).lower():
                    raise QueryTimeout(f"Превышено время выполнения ({timeout_s} с)") from exc
                raise ConnectorError(str(exc)) from exc
            finally:
                self._threads.pop(query_id, None)
        return QueryResult(
            columns=[ResultColumn(d[0], str(d[1])) for d in desc],
            rows=[list(r) for r in rows[:limit]],
            truncated=len(rows) > limit,
            elapsed_ms=round((time.perf_counter() - start) * 1000, 1),
        )

    async def cancel(self, query_id: str) -> None:
        tid = self._threads.get(query_id)
        if tid and self._pool is not None:
            async with self._pool.acquire() as conn, conn.cursor() as cur:
                await cur.execute(f"KILL QUERY {int(tid)}")

    async def close(self) -> None:
        if self._pool is not None:
            self._pool.close()
            await asyncio.wait_for(self._pool.wait_closed(), 5)
            self._pool = None
