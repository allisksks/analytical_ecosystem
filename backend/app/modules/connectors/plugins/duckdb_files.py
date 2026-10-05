"""Files (CSV, XLSX, Parquet) and S3-compatible object storage, queried through an embedded DuckDB.

Every file becomes a view named after the file (``events.parquet`` -> ``events``). Arbitrary file
access from SQL is impossible: the query guard forbids table functions, and DuckDB runs with
``enable_external_access`` disabled after the views are created.
"""

from __future__ import annotations

import asyncio
import re
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, ClassVar

import duckdb

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

SUPPORTED = {".parquet": "read_parquet", ".csv": "read_csv_auto", ".tsv": "read_csv_auto", ".xlsx": "read_xlsx"}
_IDENT = re.compile(r"[^a-zA-Z0-9_]")


def view_name(path: Path) -> str:
    name = _IDENT.sub("_", path.stem).lower()
    return name if not name[:1].isdigit() else f"t_{name}"


class _Running:
    def __init__(self) -> None:
        self.conns: dict[str, duckdb.DuckDBPyConnection] = {}
        self.lock = threading.Lock()


class DuckDBBase(Connector):
    dialect = "duckdb"
    _running: ClassVar[_Running] = _Running()

    def _views(self) -> dict[str, str]:
        """view name -> SQL source expression."""
        raise NotImplementedError

    def _setup(self, con: duckdb.DuckDBPyConnection) -> None:
        """Extensions / credentials before views are created."""

    def _allowed_dirs(self) -> list[str]:
        raise NotImplementedError

    def _connect(self) -> duckdb.DuckDBPyConnection:
        con = duckdb.connect(":memory:", config={"threads": 2, "memory_limit": "2GB"})
        self._setup(con)
        for name, source in self._views().items():
            con.execute(f'CREATE VIEW "{name}" AS SELECT * FROM {source}')
        # from now on SQL can read only the source's own files/bucket
        con.execute("SET allowed_directories = ?", [self._allowed_dirs()])
        con.execute("SET enable_external_access = false")
        con.execute("SET lock_configuration = true")
        return con

    async def _ping(self) -> str:
        def run() -> str:
            con = self._connect()
            try:
                row = con.execute("SELECT version()").fetchone()
                return f"DuckDB {row[0] if row else ''}, {len(self._views())} files"
            finally:
                con.close()

        return await asyncio.to_thread(run)

    async def list_catalog(self) -> list[TableMeta]:
        def run() -> list[TableMeta]:
            con = self._connect()
            try:
                tables = []
                for name in self._views():
                    cols = con.execute(f'DESCRIBE "{name}"').fetchall()
                    count_row = con.execute(f'SELECT count(*) FROM "{name}"').fetchone()
                    tables.append(
                        TableMeta(
                            schema="main",
                            name=name,
                            kind="view",
                            columns=[ColumnMeta(c[0], str(c[1]), c[2] == "YES") for c in cols],
                            row_count=int(count_row[0]) if count_row else None,
                            last_modified=self._modified(name),
                        )
                    )
                return tables
            finally:
                con.close()

        return await asyncio.to_thread(run)

    def _modified(self, _name: str) -> datetime | None:
        return None

    async def execute(
        self, sql: str, params: dict[str, Any] | None, limit: int, timeout_s: int, query_id: str
    ) -> QueryResult:
        running = self._running

        def run() -> QueryResult:
            con = self._connect()
            with running.lock:
                running.conns[query_id] = con
            start = time.perf_counter()
            try:
                cur = con.execute(sql, params or {})
                rows = cur.fetchmany(limit + 1)
                desc = cur.description or []
                return QueryResult(
                    columns=[ResultColumn(d[0], str(d[1])) for d in desc],
                    rows=[list(r) for r in rows[:limit]],
                    truncated=len(rows) > limit,
                    elapsed_ms=round((time.perf_counter() - start) * 1000, 1),
                )
            except duckdb.InterruptException as exc:
                raise QueryCancelled("Запрос отменён") from exc
            except duckdb.Error as exc:
                raise ConnectorError(str(exc).split("\n")[0]) from exc
            finally:
                with running.lock:
                    running.conns.pop(query_id, None)
                con.close()

        task = asyncio.create_task(asyncio.to_thread(run))
        try:
            return await asyncio.wait_for(asyncio.shield(task), timeout_s)
        except TimeoutError as exc:
            await self.cancel(query_id)
            await asyncio.gather(task, return_exceptions=True)
            raise QueryTimeout(f"Превышено время выполнения ({timeout_s} с)") from exc

    async def cancel(self, query_id: str) -> None:
        with self._running.lock:
            con = self._running.conns.get(query_id)
        if con is not None:
            con.interrupt()


class FilesConnector(DuckDBBase):
    """Local directory with uploaded files (or the bundled demo data)."""

    type = "files"
    title = "Файлы: CSV, XLSX, Parquet"
    config_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "required": [],
        "properties": {
            "path": schema_prop(
                "Каталог с файлами",
                description="Каталог на сервере платформы. Пусто — файлы загружаются через интерфейс",
            ),
        },
    }

    @property
    def root(self) -> Path:
        return Path(self.config.get("path") or self.config["_storage_dir"]).expanduser()

    def _files(self) -> list[Path]:
        if not self.root.is_dir():
            raise ConnectorError(f"Каталог {self.root} не найден")
        return sorted(p for p in self.root.iterdir() if p.suffix.lower() in SUPPORTED and not p.name.startswith("_"))

    def _views(self) -> dict[str, str]:
        out: dict[str, str] = {}
        for p in self._files():
            reader = SUPPORTED[p.suffix.lower()]
            literal = str(p.resolve()).replace("'", "''")
            out[view_name(p)] = f"{reader}('{literal}')"
        return out

    def _allowed_dirs(self) -> list[str]:
        return [str(self.root.resolve()) + "/"]

    def _setup(self, con: duckdb.DuckDBPyConnection) -> None:
        if any(p.suffix.lower() == ".xlsx" for p in self._files()):
            con.execute("INSTALL excel; LOAD excel;")

    def _modified(self, name: str) -> datetime | None:
        for p in self._files():
            if view_name(p) == name:
                return datetime.fromtimestamp(p.stat().st_mtime, UTC)
        return None


class S3Connector(DuckDBBase):
    """S3-compatible storage (MinIO, Yandex Object Storage, VK Cloud S3) via DuckDB httpfs, live mode."""

    type = "s3"
    title = "S3-совместимое хранилище"
    secret_fields = ("secret_access_key",)
    config_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "required": ["endpoint", "bucket", "access_key_id", "secret_access_key"],
        "properties": {
            "endpoint": schema_prop("Endpoint", default="storage.yandexcloud.net"),
            "region": schema_prop("Регион", default="ru-central1"),
            "bucket": schema_prop("Бакет"),
            "prefix": schema_prop("Префикс", default=""),
            "url_style": schema_prop("Стиль адресации", enum=["path", "vhost"], default="path"),
            "use_ssl": schema_prop("TLS", type_="boolean", default=True),
            "access_key_id": schema_prop("Access key ID"),
            "secret_access_key": schema_prop("Secret access key", secret=True),
            "tables": {
                "type": "object",
                "title": "Таблицы",
                "description": 'Имя таблицы → путь/маска внутри бакета, например {"events": "events/*.parquet"}',
                "additionalProperties": {"type": "string"},
            },
        },
    }

    def _setup(self, con: duckdb.DuckDBPyConnection) -> None:
        con.execute("INSTALL httpfs; LOAD httpfs;")
        con.execute(
            "CREATE SECRET s3src (TYPE s3, KEY_ID ?, SECRET ?, REGION ?, ENDPOINT ?, URL_STYLE ?, USE_SSL ?)",
            [
                self.config["access_key_id"],
                self.secrets.get("secret_access_key", ""),
                self.config.get("region", "us-east-1"),
                self.config["endpoint"],
                self.config.get("url_style", "path"),
                bool(self.config.get("use_ssl", True)),
            ],
        )

    def _allowed_dirs(self) -> list[str]:
        return [f"s3://{self.config['bucket']}/"]

    def _views(self) -> dict[str, str]:
        bucket = self.config["bucket"]
        prefix = self.config.get("prefix", "").strip("/")
        out = {}
        for name, pattern in (self.config.get("tables") or {}).items():
            path = "/".join(x for x in (prefix, str(pattern).lstrip("/")) if x)
            url = f"s3://{bucket}/{path}".replace("'", "''")
            reader = "read_csv_auto" if url.endswith((".csv", ".tsv")) else "read_parquet"
            out[_IDENT.sub("_", name).lower()] = f"{reader}('{url}')"
        return out
