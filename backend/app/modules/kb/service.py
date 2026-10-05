"""Knowledge base use-cases: visibility, versioned edits, full-text search with facets, starter content."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

import yaml
from sqlalchemy import ColumnElement, Select, Text, and_, cast, func, literal, or_, select
from sqlalchemy.dialects.postgresql import TSQUERY
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFoundError, PermissionDenied, ValidationFailed
from app.modules.iam.models import Project
from app.modules.iam.permissions import P
from app.modules.iam.policy import Principal
from app.modules.kb.models import KB_TYPES, KnowledgeItem, KnowledgeVersion
from app.modules.semantic.service import PACKS_DIR


def visibility(principal: Principal) -> ColumnElement[bool]:
    """Org-wide items for anyone who may read the KB somewhere; project items only inside readable projects."""
    projects = principal.projects_with(P.KB_VIEW)
    cond: ColumnElement[bool] = KnowledgeItem.org_id == principal.org_id
    if projects is None:
        return cond
    if not projects:
        return and_(cond, literal(False))
    return and_(cond, or_(KnowledgeItem.project_id.is_(None), KnowledgeItem.project_id.in_(projects)))


def can_read(principal: Principal, item: KnowledgeItem) -> bool:
    if item.org_id != principal.org_id:
        return False
    if item.project_id is None:
        return principal.can_anywhere(P.KB_VIEW)
    return principal.can(P.KB_VIEW, item.project_id)


def require_write(principal: Principal, project_id: uuid.UUID | None) -> None:
    if project_id is None:
        if not principal.can_anywhere(P.KB_WRITE):
            raise PermissionDenied("Нет прав на запись в базу знаний", details={"permission": P.KB_WRITE})
    else:
        principal.require(P.KB_WRITE, project_id)


def can_edit(principal: Principal, item: KnowledgeItem) -> bool:
    if principal.can(P.KB_MODERATE, item.project_id) or (
        item.project_id is None and principal.can_anywhere(P.KB_MODERATE)
    ):
        return True
    own = item.author_id == principal.id
    return own and (
        principal.can(P.KB_WRITE, item.project_id) or (item.project_id is None and principal.can_anywhere(P.KB_WRITE))
    )


async def get_item(db: AsyncSession, principal: Principal, item_id: uuid.UUID) -> KnowledgeItem:
    item = await db.get(KnowledgeItem, item_id)
    if item is None or not can_read(principal, item):
        raise NotFoundError("Запись не найдена")
    if item.status == "draft" and not can_edit(principal, item):
        raise NotFoundError("Запись не найдена")
    return item


def validate_type(t: str) -> None:
    if t not in KB_TYPES:
        raise ValidationFailed(f"Неизвестный тип записи: {t}", details={"allowed": list(KB_TYPES)})


async def snapshot(db: AsyncSession, item: KnowledgeItem, author: str) -> None:
    db.add(
        KnowledgeVersion(
            item_id=item.id, version=item.version, title=item.title, summary=item.summary, body=item.body, author=author
        )
    )


async def create_item(
    db: AsyncSession,
    principal: Principal | None,
    *,
    org_id: uuid.UUID,
    project_id: uuid.UUID | None,
    type: str,
    title: str,
    summary: str = "",
    body: str = "",
    tags: list[str] | None = None,
    links: list[dict[str, Any]] | None = None,
    decision: str = "",
    status: str = "published",
    author_name: str | None = None,
    source_ref: str = "",
) -> KnowledgeItem:
    validate_type(type)
    item = KnowledgeItem(
        org_id=org_id,
        project_id=project_id,
        type=type,
        title=title,
        summary=summary,
        body=body,
        tags=sorted({t.strip().lower().lstrip("#") for t in (tags or []) if t.strip()}),
        links=links or [],
        decision=decision,
        status=status,
        author_id=principal.id if principal and principal.kind == "user" else None,
        author_name=author_name or (principal.label if principal else "system"),
        source_ref=source_ref,
        version=1,
    )
    db.add(item)
    await db.flush()
    await snapshot(db, item, item.author_name)
    return item


@dataclass
class SearchParams:
    q: str = ""
    types: list[str] | None = None
    project_id: uuid.UUID | None = None
    tags: list[str] | None = None
    status: str = "published"
    sort: str = "relevance"
    limit: int = 30
    offset: int = 0


def _base(
    principal: Principal, params: SearchParams, include_tags: bool = True, include_types: bool = True
) -> Select[Any]:
    q = select(KnowledgeItem).where(visibility(principal))
    if params.status != "all":
        q = q.where(KnowledgeItem.status == params.status)
    if params.project_id:
        q = q.where(or_(KnowledgeItem.project_id == params.project_id, KnowledgeItem.project_id.is_(None)))
    if include_types and params.types:
        q = q.where(KnowledgeItem.type.in_(params.types))
    if include_tags and params.tags:
        q = q.where(KnowledgeItem.tags.contains(params.tags))
    if params.q.strip():
        q = q.where(_match(params.q))
    return q


def _tsquery(text: str) -> Any:
    """Explicit syntax ("quotes", -minus, or) is honoured; a plain question matches ANY of its lemmas
    and relevance ranking puts records matching more of them first."""
    if any(c in text for c in '"-') or " or " in text.lower():
        return func.websearch_to_tsquery("russian", text)
    anded = cast(func.plainto_tsquery("russian", text), Text)
    return cast(func.replace(anded, "&", "|"), TSQUERY)


def _match(text: str) -> ColumnElement[bool]:
    return or_(
        KnowledgeItem.search.op("@@")(_tsquery(text)),
        KnowledgeItem.title.op("%")(text),
        KnowledgeItem.title.ilike(f"%{text}%"),
    )


async def search(db: AsyncSession, principal: Principal, params: SearchParams) -> dict[str, Any]:
    base = _base(principal, params)
    total = await db.scalar(select(func.count()).select_from(base.subquery())) or 0
    q = base
    if params.q.strip() and params.sort == "relevance":
        rank = func.ts_rank_cd(KnowledgeItem.search, _tsquery(params.q)) + func.similarity(
            KnowledgeItem.title, params.q
        )
        q = q.order_by(rank.desc(), KnowledgeItem.updated_at.desc())
    else:
        q = q.order_by(KnowledgeItem.created_at.desc())
    items = list((await db.execute(q.limit(params.limit).offset(params.offset))).scalars())

    by_type = _base(principal, params, include_types=False).subquery()
    type_counts: dict[str, int] = dict(
        (await db.execute(select(by_type.c.type, func.count()).group_by(by_type.c.type))).all()
    )
    by_tag = _base(principal, params, include_tags=False).subquery()
    tag = func.unnest(by_tag.c.tags).label("tag")
    tag_rows = (
        await db.execute(
            select(tag, func.count()).select_from(by_tag).group_by(tag).order_by(func.count().desc(), tag).limit(40)
        )
    ).all()
    return {
        "items": items,
        "total": total,
        "facets": {
            "types": {t: int(type_counts.get(t, 0)) for t in KB_TYPES},
            "tags": [{"tag": t, "count": n} for t, n in tag_rows],
        },
    }


def kb_pack(pack: str = "gaming") -> dict[str, Any]:
    path = PACKS_DIR / pack / "kb.yaml"
    return yaml.safe_load(path.read_text(encoding="utf-8")) if path.exists() else {"templates": {}, "examples": []}


async def install_examples(
    db: AsyncSession, org_id: uuid.UUID, projects: dict[str, Project], pack: str = "gaming"
) -> int:
    data = kb_pack(pack)
    n = 0
    for ex in data.get("examples", []):
        project = projects.get(ex.get("project", "")) if ex.get("project") else None
        await create_item(
            db,
            None,
            org_id=org_id,
            project_id=project.id if project else None,
            type=ex["type"],
            title=ex["title"],
            summary=ex.get("summary", ""),
            body=ex.get("body") or data["templates"].get(ex["type"], ""),
            tags=ex.get("tags", []),
            links=ex.get("links", []),
            decision=ex.get("decision", ""),
            author_name=ex.get("author", "starter-kit"),
        )
        n += 1
    return n
