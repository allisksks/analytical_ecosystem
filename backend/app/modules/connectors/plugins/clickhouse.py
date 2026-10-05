"""ClickHouse (live mode, HTTP interface via clickhouse-connect)."""

from __future__ import annotations

import time
from datetime import UTC
from typing import Any, ClassVar

import clickhouse_connect
from clickhouse_connect.driver.exceptions import ClickHouseError

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

TABLES_SQL = """
SELECT database, name, engine, total_rows, metadata_modification_time, comment
FROM system.tables WHERE database = {db:String} AND NOT is_temporary
"""
COLUMNS_SQL = """
SELECT table, name, type, comment FROM system.columns WHERE database = {db:String} ORDER BY table, position
"""


class ClickHouseConnector(Connector):
    type = "clickhouse"
    title = "ClickHouse"
    dialect = "clickhouse"
    secret_fields = ("password",)
    config_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "required": ["host", "database", "user"],
        "properties": {
            "host": schema_prop("Хост"),
            "port": schema_prop("HTTP-порт", type_="integer", default=8123),
            "database": schema_prop("База данных", default="default"),
            "user": schema_prop("Пользователь", default="default", description="Рекомендуется профиль readonly"),
            "password": schema_prop("Пароль", secret=True),
            "secure": schema_prop("TLS (HTTPS)", type_="boolean", default=False),
            "max_memory_usage_gb": schema_prop("Лимит памяти на запрос, ГБ", type_="integer", default=8, minimum=1),
        },
    }

    def __init__(self, config: dict[str, Any], secrets: dict[str, Any]) -> None:
        super().__init__(config, secrets)
        self._client: Any = None

    async def _get_client(self) -> Any:
        if self._client is None:
            try:
                self._client = await clickhouse_connect.get_async_client(
                    host=self.config["host"],
                    port=int(self.config.get("port", 8123)),
                    username=self.config.get("user", "default"),
                    password=self.secrets.get("password", ""),
                    database=self.config.get("database", "default"),
                    secure=bool(self.config.get("secure", False)),
                    connect_timeout=10,
                    send_receive_timeout=600,
                    autogenerate_session_id=False,
                )
            except (ClickHouseError, OSError) as exc:
                raise ConnectorError(str(exc)) from exc
        return self._client

    async def _ping(self) -> str:
        client = await self._get_client()
        return f"ClickHouse {client.server_version}"

    async def list_catalog(self) -> list[TableMeta]:
        client = await self._get_client()
        db = self.config.get("database", "default")
        tables = await client.query(TABLES_SQL, parameters={"db": db})
        cols = await client.query(COLUMNS_SQL, parameters={"db": db})
        by_table: dict[str, list[ColumnMeta]] = {}
        for table, name, ctype, comment in cols.result_rows:
            by_table.setdefault(table, []).append(ColumnMeta(name, ctype, ctype.startswith("Nullable"), comment))
        out = []
        for database, name, engine, total_rows, modified, comment in tables.result_rows:
            out.append(
                TableMeta(
                    schema=database,
                    name=name,
                    kind="view" if "View" in engine else "table",
                    columns=by_table.get(name, []),
                    row_count=int(total_rows) if total_rows is not None else None,
                    last_modified=modified.replace(tzinfo=UTC) if modified and modified.tzinfo is None else modified,
                    comment=comment or "",
                )
            )
        return out

    async def execute(
        self, sql: str, params: dict[str, Any] | None, limit: int, timeout_s: int, query_id: str
    ) -> QueryResult:
        client = await self._get_client()
        settings = {
            "readonly": 2,  # SELECT only, settings may be changed per query
            "max_execution_time": int(timeout_s),
            "max_result_rows": limit + 1,
            "result_overflow_mode": "break",
            "max_memory_usage": int(self.config.get("max_memory_usage_gb", 8)) * 1024**3,
        }
        start = time.perf_counter()
        try:
            res = await client.query(sql, parameters=params, settings={**settings, "query_id": query_id})
        except ClickHouseError as exc:
            msg = str(exc)
            if "TIMEOUT_EXCEEDED" in msg or "Timeout exceeded" in msg:
                raise QueryTimeout(f"Превышено время выполнения ({timeout_s} с)") from exc
            raise ConnectorError(msg.split("\n")[0][:500]) from exc
        rows = [list(r) for r in res.result_rows]
        return QueryResult(
            columns=[ResultColumn(n, t.name) for n, t in zip(res.column_names, res.column_types, strict=True)],
            rows=rows[:limit],
            truncated=len(rows) > limit,
            elapsed_ms=round((time.perf_counter() - start) * 1000, 1),
        )

    async def cancel(self, query_id: str) -> None:
        client = await self._get_client()
        await client.command("KILL QUERY WHERE query_id = {qid:String} ASYNC", parameters={"qid": query_id})

    async def close(self) -> None:
        if self._client is not None:
            await self._client.close()
            self._client = None
