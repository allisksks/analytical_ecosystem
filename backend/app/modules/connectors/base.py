"""Connector contract (TZ, section 4).

Every source type is a plugin implementing the same protocol, so a new source is added without
touching the core: JSON Schema of parameters (the UI renders the form from it), connection test,
catalog listing, query execution with limit and timeout, cancellation and the sqlglot dialect used
by the semantic layer and the query guard.
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, ClassVar, Literal

Mode = Literal["live", "sync"]


@dataclass
class TestResult:
    ok: bool
    message: str = ""
    latency_ms: float = 0.0
    server_version: str = ""


@dataclass
class ColumnMeta:
    name: str
    data_type: str
    nullable: bool = True
    comment: str = ""


@dataclass
class TableMeta:
    schema: str
    name: str
    kind: str = "table"  # table | view
    columns: list[ColumnMeta] = field(default_factory=list)
    row_count: int | None = None
    last_modified: datetime | None = None
    comment: str = ""


@dataclass
class ResultColumn:
    name: str
    type: str


@dataclass
class QueryResult:
    columns: list[ResultColumn]
    rows: list[list[Any]]
    truncated: bool = False
    elapsed_ms: float = 0.0

    @property
    def row_count(self) -> int:
        return len(self.rows)


class ConnectorError(Exception):
    """Error reported by the source (bad SQL, network, auth). Message is safe to show to the user."""


class QueryTimeout(ConnectorError):
    pass


class QueryCancelled(ConnectorError):
    pass


class Connector(ABC):
    type: ClassVar[str]
    title: ClassVar[str]
    dialect: ClassVar[str]  # sqlglot dialect
    mode: ClassVar[Mode] = "live"
    stage: ClassVar[str] = "MVP"
    config_schema: ClassVar[dict[str, Any]]
    # fields of config_schema that are secrets: stored encrypted, never returned to the client
    secret_fields: ClassVar[tuple[str, ...]] = ()

    def __init__(self, config: dict[str, Any], secrets: dict[str, Any]) -> None:
        self.config = config
        self.secrets = secrets

    async def test(self) -> TestResult:
        start = time.perf_counter()
        try:
            version = await self._ping()
        except Exception as exc:  # report, never raise: the UI shows the message
            return TestResult(False, _short(exc), (time.perf_counter() - start) * 1000)
        return TestResult(True, "OK", round((time.perf_counter() - start) * 1000, 1), version)

    @abstractmethod
    async def _ping(self) -> str:
        """Checks connectivity, returns server version."""

    @abstractmethod
    async def list_catalog(self) -> list[TableMeta]: ...

    @abstractmethod
    async def execute(
        self, sql: str, params: dict[str, Any] | None, limit: int, timeout_s: int, query_id: str
    ) -> QueryResult:
        """Runs a read-only query. Must fetch at most ``limit + 1`` rows to detect truncation.

        User values never reach the SQL text unescaped: the query service builds literals with sqlglot,
        so ``params`` is reserved for connectors that support native binding."""

    async def cancel(self, query_id: str) -> None:  # noqa: B027 - optional for sources without server-side ids
        """Cancels a running query (best effort)."""

    async def close(self) -> None:  # noqa: B027
        """Releases pools/connections."""


class SyncConnector(Connector, ABC):
    """Sources without SQL (APIs, spreadsheets): data is pulled on schedule into platform storage."""

    mode: ClassVar[Mode] = "sync"

    @abstractmethod
    def extract(self, stream: str, cursor: str | None) -> AsyncIterator[list[dict[str, Any]]]:
        """Incremental extraction by cursor (date or id)."""


def _short(exc: BaseException, limit: int = 500) -> str:
    msg = str(exc).strip() or type(exc).__name__
    return msg if len(msg) <= limit else msg[:limit] + "…"


def short_error(exc: BaseException) -> str:
    return _short(exc)


def schema_prop(
    title: str,
    *,
    type_: str = "string",
    default: Any = None,
    description: str = "",
    secret: bool = False,
    enum: list[str] | None = None,
    minimum: int | None = None,
    maximum: int | None = None,
) -> dict[str, Any]:
    prop: dict[str, Any] = {"type": type_, "title": title}
    if default is not None:
        prop["default"] = default
    if description:
        prop["description"] = description
    if secret:
        prop["format"] = "password"
        prop["writeOnly"] = True
    if enum:
        prop["enum"] = enum
    if minimum is not None:
        prop["minimum"] = minimum
    if maximum is not None:
        prop["maximum"] = maximum
    return prop
