"""Knowledge base API: search with facets, CRUD with versions, comments, attachments, templates."""

from __future__ import annotations

import re
import uuid
from typing import Annotated

import anyio
from fastapi import APIRouter, Query, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import select

from app.core.config import get_settings
from app.core.errors import NotFoundError, PermissionDenied, ValidationFailed
from app.modules.audit.service import record
from app.modules.iam.deps import DB, CurrentPrincipal
from app.modules.iam.permissions import P
from app.modules.kb import service
from app.modules.kb.models import KnowledgeAttachment, KnowledgeComment, KnowledgeItem, KnowledgeVersion
from app.modules.kb.schemas import (
    AttachmentOut,
    ItemIn,
    ItemOut,
    ItemPatch,
    ItemSummary,
    KbCommentIn,
    KbCommentOut,
    KbVersionOut,
    SearchOut,
)
from app.modules.query.service import load_project

router = APIRouter(prefix="/kb", tags=["knowledge base"])
MAX_ATTACHMENT = 50 * 1024 * 1024
ALLOWED_CT = re.compile(
    r"^(image/(png|jpeg|gif|webp)|application/pdf|text/(csv|plain|markdown)|application/vnd\.openxmlformats.*)$"
)


@router.get("/templates", response_model=dict[str, str], summary="Markdown skeletons per record type")
async def templates(_: CurrentPrincipal) -> dict[str, str]:
    return dict(service.kb_pack().get("templates", {}))


@router.get("", response_model=SearchOut, summary="Full-text search with type and tag facets")
async def search(
    principal: CurrentPrincipal,
    db: DB,
    q: str = "",
    type: Annotated[list[str] | None, Query()] = None,
    tag: Annotated[list[str] | None, Query()] = None,
    project_id: uuid.UUID | None = None,
    status: str = "published",
    sort: str = "relevance",
    limit: Annotated[int, Query(ge=1, le=100)] = 30,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> SearchOut:
    if not principal.can_anywhere(P.KB_VIEW):
        raise PermissionDenied("Нет доступа к базе знаний", details={"permission": P.KB_VIEW})
    res = await service.search(
        db,
        principal,
        service.SearchParams(
            q=q[:300], types=type, project_id=project_id, tags=tag, status=status, sort=sort, limit=limit, offset=offset
        ),
    )
    return SearchOut(
        items=[ItemSummary.model_validate(i) for i in res["items"]], total=res["total"], facets=res["facets"]
    )


async def _full(db: DB, principal: CurrentPrincipal, item: KnowledgeItem) -> ItemOut:
    comments = (
        await db.execute(
            select(KnowledgeComment).where(KnowledgeComment.item_id == item.id).order_by(KnowledgeComment.created_at)
        )
    ).scalars()
    files = (await db.execute(select(KnowledgeAttachment).where(KnowledgeAttachment.item_id == item.id))).scalars()
    out = ItemOut.model_validate(item)
    out.can_edit = service.can_edit(principal, item)
    out.comments = [KbCommentOut.model_validate(c) for c in comments]
    out.attachments = [AttachmentOut.model_validate(f) for f in files]
    return out


@router.post("", response_model=ItemOut, status_code=201)
async def create(body: ItemIn, principal: CurrentPrincipal, db: DB) -> ItemOut:
    if body.project_id:
        await load_project(db, principal, body.project_id)
    service.require_write(principal, body.project_id)
    item = await service.create_item(
        db,
        principal,
        org_id=principal.org_id,
        project_id=body.project_id,
        type=body.type,
        title=body.title,
        summary=body.summary,
        body=body.body,
        tags=body.tags,
        links=[x.model_dump() for x in body.links],
        decision=body.decision,
        status=body.status,
    )
    await record(
        db, "kb.create", principal=principal, resource_type="kb_item", resource_id=item.id, project_id=item.project_id
    )
    await db.commit()
    await db.refresh(item)
    return await _full(db, principal, item)


@router.get("/{item_id}", response_model=ItemOut)
async def read(item_id: uuid.UUID, principal: CurrentPrincipal, db: DB) -> ItemOut:
    return await _full(db, principal, await service.get_item(db, principal, item_id))


@router.patch("/{item_id}", response_model=ItemOut, summary="Edit (content changes create a new version)")
async def update(item_id: uuid.UUID, body: ItemPatch, principal: CurrentPrincipal, db: DB) -> ItemOut:
    item = await service.get_item(db, principal, item_id)
    if not service.can_edit(principal, item):
        raise PermissionDenied("Редактировать может автор или модератор", details={"permission": P.KB_MODERATE})
    changes = body.model_dump(exclude_unset=True)
    if "tags" in changes:
        changes["tags"] = sorted({t.strip().lower().lstrip("#") for t in changes["tags"] if t.strip()})
    content_changed = any(k in changes and changes[k] != getattr(item, k) for k in ("title", "summary", "body"))
    for k, v in changes.items():
        setattr(item, k, v)
    if content_changed:
        item.version += 1
        await service.snapshot(db, item, principal.label)
    await record(
        db,
        "kb.update",
        principal=principal,
        resource_type="kb_item",
        resource_id=item.id,
        project_id=item.project_id,
        details={"fields": sorted(changes), "version": item.version},
    )
    await db.commit()
    await db.refresh(item)
    return await _full(db, principal, item)


@router.get("/{item_id}/versions", response_model=list[KbVersionOut])
async def versions(item_id: uuid.UUID, principal: CurrentPrincipal, db: DB) -> list[KnowledgeVersion]:
    await service.get_item(db, principal, item_id)
    q = select(KnowledgeVersion).where(KnowledgeVersion.item_id == item_id).order_by(KnowledgeVersion.version.desc())
    return list((await db.execute(q)).scalars())


@router.post("/{item_id}/comments", response_model=KbCommentOut, status_code=201)
async def comment(item_id: uuid.UUID, body: KbCommentIn, principal: CurrentPrincipal, db: DB) -> KnowledgeComment:
    item = await service.get_item(db, principal, item_id)
    c = KnowledgeComment(item_id=item.id, author_id=principal.id, author_name=principal.label, text=body.text)
    db.add(c)
    await db.commit()
    await db.refresh(c)
    return c


@router.post("/{item_id}/attachments", response_model=AttachmentOut, status_code=201)
async def attach(item_id: uuid.UUID, file: UploadFile, principal: CurrentPrincipal, db: DB) -> KnowledgeAttachment:
    item = await service.get_item(db, principal, item_id)
    if not service.can_edit(principal, item):
        raise PermissionDenied("Вложения добавляет автор или модератор")
    ct = file.content_type or "application/octet-stream"
    if not ALLOWED_CT.match(ct):
        raise ValidationFailed("Допустимы изображения, PDF, CSV, текст и документы Office")
    name = re.sub(r"[^\w.\-]", "_", file.filename or "file")[:200]
    folder = anyio.Path(get_settings().storage_dir) / "kb" / str(item.id)
    await folder.mkdir(parents=True, exist_ok=True)
    att = KnowledgeAttachment(
        item_id=item.id, filename=name, content_type=ct, size=0, path="", uploaded_by=principal.label
    )
    db.add(att)
    await db.flush()
    path = folder / f"{att.id}"
    size = 0
    async with await anyio.open_file(path, "wb") as fh:
        while chunk := await file.read(1024 * 1024):
            size += len(chunk)
            if size > MAX_ATTACHMENT:
                break
            await fh.write(chunk)
    if size > MAX_ATTACHMENT:
        await path.unlink(missing_ok=True)
        raise ValidationFailed("Файл больше 50 МБ")
    att.size, att.path = size, str(await path.resolve())
    await db.commit()
    await db.refresh(att)
    return att


@router.get("/{item_id}/attachments/{attachment_id}", response_class=FileResponse)
async def download(item_id: uuid.UUID, attachment_id: uuid.UUID, principal: CurrentPrincipal, db: DB) -> FileResponse:
    await service.get_item(db, principal, item_id)
    att = await db.get(KnowledgeAttachment, attachment_id)
    if att is None or att.item_id != item_id:
        raise NotFoundError("Вложение не найдено")
    return FileResponse(att.path, media_type=att.content_type, filename=att.filename)
