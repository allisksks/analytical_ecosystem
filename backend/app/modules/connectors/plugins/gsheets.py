"""Google Sheets (sync mode): sheets are pulled on demand/schedule into Parquet and queried via DuckDB."""

from __future__ import annotations

import json
import time
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any, ClassVar

import httpx
import jwt
import pyarrow as pa
import pyarrow.parquet as pq

from app.modules.connectors.base import ConnectorError, SyncConnector, schema_prop
from app.modules.connectors.plugins.duckdb_files import FilesConnector, view_name

TOKEN_URL = "https://oauth2.googleapis.com/token"
API = "https://sheets.googleapis.com/v4/spreadsheets"
SCOPE = "https://www.googleapis.com/auth/spreadsheets.readonly"


class GoogleSheetsConnector(FilesConnector, SyncConnector):
    type = "gsheets"
    title = "Google Sheets"
    dialect = "duckdb"
    mode = "sync"
    secret_fields = ("service_account_json",)
    config_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "required": ["spreadsheet_id", "service_account_json"],
        "properties": {
            "spreadsheet_id": schema_prop("ID таблицы", description="Часть ссылки между /d/ и /edit"),
            "sheets": schema_prop("Листы через запятую", default="", description="Пусто — все листы"),
            "service_account_json": schema_prop(
                "JSON ключ сервисного аккаунта",
                secret=True,
                description="Откройте таблице доступ на чтение для e-mail сервисного аккаунта",
            ),
        },
    }
    transport: ClassVar[httpx.AsyncBaseTransport | None] = None  # tests inject a mock

    @property
    def root(self) -> Path:
        return Path(self.config["_storage_dir"])

    def _files(self) -> list[Path]:
        if not self.root.is_dir():
            raise ConnectorError("Данные ещё не синхронизированы — нажмите «Синхронизировать»")
        return super()._files()

    async def _token(self, client: httpx.AsyncClient) -> str:
        try:
            sa = json.loads(self.secrets["service_account_json"])
        except (KeyError, json.JSONDecodeError) as exc:
            raise ConnectorError("Некорректный JSON ключ сервисного аккаунта") from exc
        now = int(time.time())
        assertion = jwt.encode(
            {"iss": sa["client_email"], "scope": SCOPE, "aud": TOKEN_URL, "iat": now, "exp": now + 3600},
            sa["private_key"],
            algorithm="RS256",
        )
        r = await client.post(
            TOKEN_URL, data={"grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer", "assertion": assertion}
        )
        if r.status_code != 200:
            raise ConnectorError(f"Google OAuth: {r.text[:300]}")
        return str(r.json()["access_token"])

    async def _sheet_titles(self, client: httpx.AsyncClient) -> list[str]:
        wanted = [s.strip() for s in str(self.config.get("sheets", "")).split(",") if s.strip()]
        if wanted:
            return wanted
        r = await client.get(f"{API}/{self.config['spreadsheet_id']}", params={"fields": "sheets.properties.title"})
        if r.status_code != 200:
            raise ConnectorError(f"Google Sheets: {r.text[:300]}")
        return [s["properties"]["title"] for s in r.json().get("sheets", [])]

    async def extract(self, stream: str, cursor: str | None) -> AsyncIterator[list[dict[str, Any]]]:
        async with httpx.AsyncClient(transport=self.transport, timeout=60) as client:
            client.headers["Authorization"] = f"Bearer {await self._token(client)}"
            r = await client.get(f"{API}/{self.config['spreadsheet_id']}/values/{stream}")
            if r.status_code != 200:
                raise ConnectorError(f"Google Sheets: {r.text[:300]}")
            values = r.json().get("values", [])
        if not values:
            return
        header = [str(h).strip() or f"col_{i}" for i, h in enumerate(values[0])]
        yield [{h: (row[i] if i < len(row) else None) for i, h in enumerate(header)} for row in values[1:]]

    async def sync(self) -> dict[str, int]:
        """Full refresh of every sheet into Parquet (sheets are small; no cursor needed)."""
        self.root.mkdir(parents=True, exist_ok=True)
        async with httpx.AsyncClient(transport=self.transport, timeout=60) as client:
            client.headers["Authorization"] = f"Bearer {await self._token(client)}"
            titles = await self._sheet_titles(client)
        counts: dict[str, int] = {}
        for title in titles:
            rows: list[dict[str, Any]] = []
            async for batch in self.extract(title, None):
                rows.extend(batch)
            table = pa.Table.from_pylist(rows) if rows else pa.table({})
            path = self.root / f"{view_name(Path(title))}.parquet"
            pq.write_table(table, path)
            counts[path.stem] = len(rows)
        return counts

    async def _ping(self) -> str:
        async with httpx.AsyncClient(transport=self.transport, timeout=30) as client:
            client.headers["Authorization"] = f"Bearer {await self._token(client)}"
            titles = await self._sheet_titles(client)
        return f"Google Sheets: {len(titles)} листов"
