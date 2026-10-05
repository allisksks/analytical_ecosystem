"""Data source lifecycle: create/update with encrypted secrets, live connector pool, catalog refresh."""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.crypto import decrypt_json, encrypt_json
from app.core.errors import NotFoundError, PermissionDenied
from app.modules.connectors.base import Connector, TableMeta
from app.modules.connectors.models import CatalogColumn, CatalogTable, DataSource
from app.modules.connectors.registry import instantiate, plugin
from app.modules.iam.permissions import P
from app.modules.iam.policy import Principal
from app.modules.query.guard import TableInfo

PII_HINTS = ("email", "e_mail", "phone", "device_id", "idfa", "gaid", "ip", "ip_address", "passport", "full_name")


class ConnectorPool:
    """One live connector (with its connection pool) per data source and version of its settings."""

    def __init__(self) -> None:
        self._items: dict[uuid.UUID, tuple[datetime, Connector]] = {}
        self._semaphores: dict[uuid.UUID, asyncio.Semaphore] = {}
        self._lock = asyncio.Lock()

    async def get(self, source: DataSource) -> Connector:
        async with self._lock:
            item = self._items.get(source.id)
            if item and item[0] == source.updated_at:
                return item[1]
            if item:
                await item[1].close()
            conn = instantiate(source.type, source.config, decrypt_json(source.secrets_encrypted), str(source.id))
            self._items[source.id] = (source.updated_at, conn)
            self._semaphores[source.id] = asyncio.Semaphore(max(1, source.max_concurrency))
            return conn

    def semaphore(self, source_id: uuid.UUID) -> asyncio.Semaphore:
        return self._semaphores.setdefault(source_id, asyncio.Semaphore(4))

    async def drop(self, source_id: uuid.UUID) -> None:
        async with self._lock:
            item = self._items.pop(source_id, None)
        if item:
            await item[1].close()

    async def close_all(self) -> None:
        for _, conn in list(self._items.values()):
            await conn.close()
        self._items.clear()


pool = ConnectorPool()


def source_allowed_in(source: DataSource, project_id: uuid.UUID | None) -> bool:
    return source.project_ids is None or (project_id is not None and project_id in source.project_ids)


async def get_source(db: AsyncSession, principal: Principal, source_id: uuid.UUID) -> DataSource:
    source = await db.get(DataSource, source_id)
    if source is None or source.org_id != principal.org_id:
        raise NotFoundError("Источник не найден")
    return source


def visible_to(principal: Principal, source: DataSource, permission: str = P.CONNECTORS_VIEW) -> bool:
    if principal.can(permission):
        return True
    projects = principal.projects_with(permission)
    if projects is None:
        return True
    if source.project_ids is None:
        return bool(projects)
    return bool(projects & set(source.project_ids))


def require_visible(principal: Principal, source: DataSource, permission: str = P.CONNECTORS_VIEW) -> None:
    if not visible_to(principal, source, permission):
        raise PermissionDenied("Нет доступа к источнику", details={"permission": permission})


def merge_secrets(source: DataSource | None, new: dict[str, Any]) -> bytes | None:
    """Empty secret fields in an update keep the stored value (the UI never receives secrets)."""
    current = decrypt_json(source.secrets_encrypted) if source else {}
    current.update({k: v for k, v in new.items() if v not in (None, "")})
    return encrypt_json(current) if current else None


def masked_config(source: DataSource) -> dict[str, Any]:
    cls = plugin(source.type)
    secrets = decrypt_json(source.secrets_encrypted)
    return {**source.config, **{k: ("••••••" if k in secrets else "") for k in cls.secret_fields}}


def _guess_pii(column: str) -> bool:
    name = column.lower()
    return any(name == h or name.endswith("_" + h) for h in PII_HINTS)


async def refresh_catalog(db: AsyncSession, source: DataSource) -> int:
    connector = await pool.get(source)
    tables: list[TableMeta] = await connector.list_catalog()
    existing = {
        (t.schema_name, t.name): t
        for t in (await db.execute(select(CatalogTable).where(CatalogTable.source_id == source.id))).scalars()
    }
    seen: set[tuple[str, str]] = set()
    for meta in tables:
        key = (meta.schema, meta.name)
        seen.add(key)
        row = existing.get(key)
        if row is None:
            row = CatalogTable(source_id=source.id, schema_name=meta.schema, name=meta.name, columns=[])
            db.add(row)
        row.kind = meta.kind
        row.row_count = meta.row_count
        row.last_modified = meta.last_modified
        row.source_comment = meta.comment
        row.present = True
        by_name = {c.name: c for c in row.columns}
        names = set()
        for i, cm in enumerate(meta.columns):
            names.add(cm.name)
            col = by_name.get(cm.name)
            if col is None:
                col = CatalogColumn(name=cm.name, is_pii=_guess_pii(cm.name))
                row.columns.append(col)
            col.data_type, col.nullable, col.ordinal, col.source_comment, col.present = (
                cm.data_type,
                cm.nullable,
                i,
                cm.comment,
                True,
            )
        for col in row.columns:
            if col.name not in names:
                col.present = False
    for key, row in existing.items():
        if key not in seen:
            row.present = False
    source.catalog_refreshed_at = datetime.now(UTC)
    await db.flush()
    return len(tables)


async def catalog_index(db: AsyncSession, source: DataSource) -> dict[tuple[str, str], TableInfo]:
    rows = (
        await db.execute(
            select(CatalogTable).where(CatalogTable.source_id == source.id, CatalogTable.present.is_(True))
        )
    ).scalars()
    out: dict[tuple[str, str], TableInfo] = {}
    for t in rows:
        cols = [c for c in t.columns if c.present]
        out[(t.schema_name.lower(), t.name.lower())] = TableInfo(
            t.schema_name, t.name, tuple(c.name for c in cols), frozenset(c.name for c in cols if c.is_pii)
        )
    return out
