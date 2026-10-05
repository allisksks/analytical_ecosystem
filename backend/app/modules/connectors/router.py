"""Data sources (connector wizard), catalog browsing and curation, file uploads, sync."""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Response, UploadFile
from sqlalchemy import func, select

from app.core.crypto import decrypt_json
from app.core.errors import NotFoundError, ValidationFailed
from app.modules.audit.service import record
from app.modules.connectors.models import CatalogColumn, CatalogTable, DataSource
from app.modules.connectors.plugins.duckdb_files import SUPPORTED
from app.modules.connectors.plugins.gsheets import GoogleSheetsConnector
from app.modules.connectors.registry import (
    PLANNED,
    PLUGINS,
    instantiate,
    plugin,
    split_secrets,
    storage_dir_for,
    validate_config,
)
from app.modules.connectors.schemas import (
    ColumnOut,
    ColumnPatch,
    ConnectorType,
    RefreshOut,
    SourceIn,
    SourceOut,
    SourcePatch,
    SourceTestIn,
    SyncOut,
    TableOut,
    TablePatch,
    TestOut,
)
from app.modules.connectors.service import (
    get_source,
    masked_config,
    merge_secrets,
    pool,
    refresh_catalog,
    require_visible,
    visible_to,
)
from app.modules.iam.deps import DB, CurrentPrincipal, require
from app.modules.iam.permissions import P
from app.modules.iam.policy import Principal
from app.modules.query.cache import get_cache

router = APIRouter(tags=["connectors"])
Manager = Annotated[Principal, Depends(require(P.CONNECTORS_MANAGE))]
MAX_UPLOAD = 200 * 1024 * 1024


def source_out(s: DataSource, table_count: int = 0) -> SourceOut:
    cls = plugin(s.type)
    return SourceOut(
        id=s.id,
        name=s.name,
        type=s.type,
        dialect=cls.dialect,
        mode=cls.mode,
        config=masked_config(s),
        project_ids=s.project_ids,
        status=s.status,
        last_error=s.last_error,
        last_tested_at=s.last_tested_at,
        catalog_refreshed_at=s.catalog_refreshed_at,
        synced_at=s.synced_at,
        timeout_s=s.timeout_s,
        row_limit=s.row_limit,
        max_concurrency=s.max_concurrency,
        cache_ttl_s=s.cache_ttl_s,
        is_demo=s.is_demo,
        table_count=table_count,
    )


@router.get("/connectors/types", response_model=list[ConnectorType], summary="Available and planned connectors")
async def connector_types(_: CurrentPrincipal) -> list[ConnectorType]:
    out = [
        ConnectorType(
            type=c.type,
            title=c.title,
            dialect=c.dialect,
            mode=c.mode,
            stage=c.stage,
            available=True,
            config_schema=c.config_schema,
            secret_fields=list(c.secret_fields),
        )
        for c in PLUGINS.values()
    ]
    out += [
        ConnectorType(type=p.type, title=p.title, mode=p.mode, stage=p.stage, available=False, kind=p.kind)
        for p in PLANNED
    ]
    return out


@router.get("/sources", response_model=list[SourceOut])
async def list_sources(principal: CurrentPrincipal, db: DB, project_id: uuid.UUID | None = None) -> list[SourceOut]:
    counts = dict(
        (
            await db.execute(
                select(CatalogTable.source_id, func.count())
                .where(CatalogTable.present.is_(True))
                .group_by(CatalogTable.source_id)
            )
        ).all()
    )
    rows = (
        await db.execute(select(DataSource).where(DataSource.org_id == principal.org_id).order_by(DataSource.name))
    ).scalars()
    out = []
    for s in rows:
        if project_id and s.project_ids is not None and project_id not in s.project_ids:
            continue
        if visible_to(principal, s) or visible_to(principal, s, P.SQL_RUN) or principal.can(P.SQL_RUN_ALL):
            out.append(source_out(s, counts.get(s.id, 0)))
    return out


@router.post("/sources/test", response_model=TestOut, summary="Check connection parameters before saving")
async def test_config(body: SourceTestIn, principal: CurrentPrincipal, db: DB) -> TestOut:
    existing = None
    if body.source_id:
        existing = await get_source(db, principal, body.source_id)
        if not principal.can(P.CONNECTORS_MANAGE):
            require_visible(principal, existing, P.CONNECTORS_CONFIGURE)
    else:
        principal.require(P.CONNECTORS_MANAGE)
    stored_keys = {k: "stored" for k in decrypt_json(existing.secrets_encrypted)} if existing else {}
    validate_config(body.type, {**stored_keys, **{k: v for k, v in body.config.items() if v not in (None, "")}})
    public, secrets = split_secrets(body.type, body.config)
    stored = decrypt_json(existing.secrets_encrypted) if existing else {}
    conn = instantiate(body.type, public, {**stored, **secrets}, str(existing.id) if existing else "probe")
    try:
        res = await conn.test()
    finally:
        await conn.close()
    return TestOut(ok=res.ok, message=res.message, latency_ms=res.latency_ms, server_version=res.server_version)


@router.post("/sources", response_model=SourceOut, status_code=201)
async def create_source(body: SourceIn, principal: Manager, db: DB) -> SourceOut:
    validate_config(body.type, body.config)
    public, secrets = split_secrets(body.type, body.config)
    source = DataSource(
        org_id=principal.org_id,
        name=body.name,
        type=body.type,
        config=public,
        project_ids=body.project_ids,
        timeout_s=body.timeout_s,
        row_limit=body.row_limit,
        max_concurrency=body.max_concurrency,
        cache_ttl_s=body.cache_ttl_s,
        created_by=principal.id,
        secrets_encrypted=merge_secrets(None, secrets),
    )
    db.add(source)
    await db.flush()
    await record(
        db,
        "source.create",
        principal=principal,
        resource_type="data_source",
        resource_id=source.id,
        details={"type": body.type, "name": body.name, "config": public},
    )
    await db.commit()
    await db.refresh(source)
    return source_out(source)


@router.get("/sources/{source_id}", response_model=SourceOut)
async def read_source(source_id: uuid.UUID, principal: CurrentPrincipal, db: DB) -> SourceOut:
    source = await get_source(db, principal, source_id)
    require_visible(principal, source)
    return source_out(source)


@router.patch("/sources/{source_id}", response_model=SourceOut)
async def update_source(source_id: uuid.UUID, body: SourcePatch, principal: CurrentPrincipal, db: DB) -> SourceOut:
    source = await get_source(db, principal, source_id)
    if not principal.can(P.CONNECTORS_MANAGE):
        require_visible(principal, source, P.CONNECTORS_CONFIGURE)
        if body.config is not None and any(
            k in plugin(source.type).secret_fields and v for k, v in body.config.items()
        ):
            principal.require(P.CONNECTORS_MANAGE)  # only managers may replace secrets
        if body.project_ids is not None or body.all_projects:
            principal.require(P.CONNECTORS_MANAGE)
    changes = body.model_dump(exclude_unset=True, exclude={"config", "all_projects"})
    for k, v in changes.items():
        if k == "project_ids" and v is None:
            continue
        setattr(source, k, v)
    if body.all_projects:
        source.project_ids = None
    if body.config is not None:
        public, secrets = split_secrets(source.type, body.config)
        validate_config(source.type, {**public, **{k: "x" for k in decrypt_json(source.secrets_encrypted)}, **secrets})
        source.config = public
        source.secrets_encrypted = merge_secrets(source, secrets)
    source.updated_at = datetime.now(UTC)
    await record(
        db,
        "source.update",
        principal=principal,
        resource_type="data_source",
        resource_id=source.id,
        details={
            "changes": body.model_dump(mode="json", exclude_unset=True, exclude={"config"}),
            "config_keys": sorted((body.config or {}).keys()),
        },
    )
    await db.commit()
    await pool.drop(source.id)
    return source_out(source)


@router.delete("/sources/{source_id}", status_code=204)
async def delete_source(source_id: uuid.UUID, principal: Manager, db: DB) -> Response:
    source = await get_source(db, principal, source_id)
    await pool.drop(source.id)
    await get_cache().invalidate_source(str(source.id))
    await db.delete(source)
    await record(db, "source.delete", principal=principal, resource_type="data_source", resource_id=source_id)
    await db.commit()
    return Response(status_code=204)


@router.post("/sources/{source_id}/test", response_model=TestOut)
async def test_source(source_id: uuid.UUID, principal: CurrentPrincipal, db: DB) -> TestOut:
    source = await get_source(db, principal, source_id)
    require_visible(principal, source)
    res = await (await pool.get(source)).test()
    source.status = "ok" if res.ok else "error"
    source.last_error = "" if res.ok else res.message
    source.last_tested_at = datetime.now(UTC)
    await db.commit()
    return TestOut(ok=res.ok, message=res.message, latency_ms=res.latency_ms, server_version=res.server_version)


@router.post("/sources/{source_id}/refresh-catalog", response_model=RefreshOut)
async def refresh(source_id: uuid.UUID, principal: CurrentPrincipal, db: DB) -> RefreshOut:
    source = await get_source(db, principal, source_id)
    if not visible_to(principal, source, P.CONNECTORS_CONFIGURE) and not visible_to(principal, source, P.CATALOG_EDIT):
        require_visible(principal, source, P.CONNECTORS_CONFIGURE)
    try:
        n = await refresh_catalog(db, source)
        source.status, source.last_error = "ok", ""
    except Exception as exc:
        source.status, source.last_error = "error", str(exc)[:500]
        await db.commit()
        raise ValidationFailed(f"Не удалось прочитать каталог: {source.last_error}") from exc
    await record(
        db,
        "catalog.refresh",
        principal=principal,
        resource_type="data_source",
        resource_id=source.id,
        details={"tables": n},
    )
    await db.commit()
    return RefreshOut(tables=n)


@router.post("/sources/{source_id}/sync", response_model=SyncOut, summary="Pull data of a sync source now")
async def sync_source(source_id: uuid.UUID, principal: CurrentPrincipal, db: DB) -> SyncOut:
    source = await get_source(db, principal, source_id)
    require_visible(principal, source, P.CONNECTORS_CONFIGURE)
    conn = await pool.get(source)
    if not isinstance(conn, GoogleSheetsConnector):
        raise ValidationFailed("Источник не поддерживает синхронизацию")
    rows = await conn.sync()
    source.synced_at = datetime.now(UTC)
    await refresh_catalog(db, source)
    await get_cache().invalidate_source(str(source.id))
    await record(
        db,
        "source.sync",
        principal=principal,
        resource_type="data_source",
        resource_id=source.id,
        details={"rows": rows},
    )
    await db.commit()
    return SyncOut(rows=rows)


@router.post("/sources/{source_id}/files", response_model=RefreshOut, summary="Upload a CSV/XLSX/Parquet file")
async def upload_file(source_id: uuid.UUID, file: UploadFile, principal: CurrentPrincipal, db: DB) -> RefreshOut:
    source = await get_source(db, principal, source_id)
    require_visible(principal, source, P.CONNECTORS_CONFIGURE)
    if source.type != "files" or source.config.get("path"):
        raise ValidationFailed("Загрузка доступна только для источника «Файлы» без внешнего каталога")
    name = re.sub(r"[^\w.\-]", "_", file.filename or "")
    suffix = ("." + name.rsplit(".", 1)[-1].lower()) if "." in name else ""
    if suffix not in SUPPORTED or name.startswith((".", "_")):
        raise ValidationFailed("Поддерживаются CSV, TSV, XLSX и Parquet")
    target_dir = storage_dir_for(str(source.id))
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / name
    size = 0
    with target.open("wb") as fh:
        while chunk := await file.read(1024 * 1024):
            size += len(chunk)
            if size > MAX_UPLOAD:
                fh.close()
                target.unlink(missing_ok=True)
                raise ValidationFailed("Файл больше 200 МБ")
            fh.write(chunk)
    source.updated_at = datetime.now(UTC)
    await db.flush()
    n = await refresh_catalog(db, source)
    await get_cache().invalidate_source(str(source.id))
    await record(
        db,
        "source.file_upload",
        principal=principal,
        resource_type="data_source",
        resource_id=source.id,
        details={"file": name, "bytes": size},
    )
    await db.commit()
    return RefreshOut(tables=n)


@router.post("/sources/{source_id}/purge-cache", status_code=204, summary="Delete cached results (152-FZ)")
async def purge_cache(source_id: uuid.UUID, principal: Manager, db: DB) -> Response:
    source = await get_source(db, principal, source_id)
    n = await get_cache().invalidate_source(str(source.id))
    await record(
        db,
        "source.cache_purged",
        principal=principal,
        resource_type="data_source",
        resource_id=source.id,
        details={"keys": n},
    )
    await db.commit()
    return Response(status_code=204)


# ---------------------------------------------------------------- catalog
@router.get("/sources/{source_id}/catalog", response_model=list[TableOut])
async def catalog(
    source_id: uuid.UUID, principal: CurrentPrincipal, db: DB, include_missing: bool = False
) -> list[CatalogTable]:
    source = await get_source(db, principal, source_id)
    if not (
        visible_to(principal, source, P.CATALOG_VIEW)
        or visible_to(principal, source, P.SQL_RUN)
        or principal.can(P.SQL_RUN_ALL)
    ):
        require_visible(principal, source, P.CATALOG_VIEW)
    q = (
        select(CatalogTable)
        .where(CatalogTable.source_id == source.id)
        .order_by(CatalogTable.schema_name, CatalogTable.name)
    )
    if not include_missing:
        q = q.where(CatalogTable.present.is_(True))
    return list((await db.execute(q)).scalars())


async def _catalog_table(db: DB, principal: Principal, table_id: uuid.UUID) -> CatalogTable:
    table = await db.get(CatalogTable, table_id)
    if table is None:
        raise NotFoundError("Таблица не найдена")
    source = await get_source(db, principal, table.source_id)
    require_visible(principal, source, P.CATALOG_EDIT)
    return table


@router.patch("/catalog/tables/{table_id}", response_model=TableOut)
async def update_table(table_id: uuid.UUID, body: TablePatch, principal: CurrentPrincipal, db: DB) -> CatalogTable:
    table = await _catalog_table(db, principal, table_id)
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(table, k, v)
    await record(
        db,
        "catalog.table_update",
        principal=principal,
        resource_type="catalog_table",
        resource_id=table.id,
        details=body.model_dump(exclude_unset=True),
    )
    await db.commit()
    await db.refresh(table)
    return table


@router.patch("/catalog/columns/{column_id}", response_model=ColumnOut)
async def update_column(column_id: uuid.UUID, body: ColumnPatch, principal: CurrentPrincipal, db: DB) -> CatalogColumn:
    col = await db.get(CatalogColumn, column_id)
    if col is None:
        raise NotFoundError("Колонка не найдена")
    table = await _catalog_table(db, principal, col.table_id)
    if body.is_pii is not None and body.is_pii != col.is_pii:
        # unmarking PII widens access to personal data: managers only
        if not body.is_pii:
            principal.require(P.CONNECTORS_MANAGE)
        await get_cache().invalidate_source(str(table.source_id))
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(col, k, v)
    await record(
        db,
        "catalog.column_update",
        principal=principal,
        resource_type="catalog_column",
        resource_id=col.id,
        details={"table": table.name, "column": col.name, **body.model_dump(exclude_unset=True)},
    )
    await db.commit()
    return col
