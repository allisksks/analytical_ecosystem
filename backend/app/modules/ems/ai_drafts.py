"""Tracking plan drafts from a release document: the AI proposes events, the analyst reviews them.

Accepting an item goes through the normal registry flow — a new event becomes a draft with a pending
v1.0.0, a change becomes a pending version — so the analytics lead still approves what reaches developers.
"""

from __future__ import annotations

import re
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError, NotFoundError, UpstreamError, ValidationFailed
from app.modules.ai import prompts
from app.modules.ai import service as ai_service
from app.modules.ai.gateway import get_gateway
from app.modules.ems import semver, service
from app.modules.ems.models import PARAM_TYPES, Event, TrackingDraft, TrackingDraftItem
from app.modules.iam.models import Project
from app.modules.iam.permissions import P
from app.modules.iam.policy import Principal

TYPE_ALIASES = {
    "integer": "int",
    "number": "float",
    "double": "float",
    "boolean": "bool",
    "str": "string",
    "datetime": "timestamp",
    "date": "timestamp",
    "object": "json",
    "array": "json",
    "list": "json",
}


def snake(name: str) -> str:
    s = re.sub(r"(?<=[a-z0-9])([A-Z])", r"_\1", str(name).strip())
    s = re.sub(r"[^a-zA-Z0-9]+", "_", s).strip("_").lower()
    if not re.search(r"[a-z]", s):  # "123", "!!!" or a Cyrillic-only name: nothing usable
        return ""
    if not s[0].isalpha():
        s = "e_" + s
    return s[:64]


def clean_params(raw: Any, global_names: set[str], warnings: list[str]) -> list[dict[str, Any]]:
    """Coerces model output into valid parameters; anything unusable becomes a warning, not an error."""
    out: dict[str, dict[str, Any]] = {}
    for p in raw if isinstance(raw, list) else []:
        if not isinstance(p, dict):
            continue
        name = snake(p.get("name", ""))
        if not name or name in global_names:
            continue
        ptype = str(p.get("type", "string")).lower()
        ptype = TYPE_ALIASES.get(ptype, ptype)
        if ptype not in PARAM_TYPES:
            warnings.append(f"Параметр {name}: тип «{ptype}» заменён на string")
            ptype = "string"
        enum = [str(v) for v in p.get("enum") or [] if str(v).strip()]
        if ptype == "enum" and not enum:
            warnings.append(f"Параметр {name}: не указаны значения enum, тип заменён на string")
            ptype = "string"
        out[name] = {
            "name": name,
            "type": ptype,
            "required": bool(p.get("required", False)),
            "description": str(p.get("description", ""))[:500],
            "enum": enum if ptype == "enum" else [],
        }
    return list(out.values())


def merge_params(current: list[dict[str, Any]], proposed: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_name = {p["name"]: dict(p) for p in current}
    for p in proposed:
        by_name[p["name"]] = {**by_name.get(p["name"], {}), **p}
    return list(by_name.values())


async def create_draft(
    db: AsyncSession,
    principal: Principal,
    project: Project,
    *,
    title: str,
    filename: str,
    text: str,
    truncated: bool,
    app_version: str,
) -> TrackingDraft:
    principal.require(P.EVENTS_EDIT, project.id)
    gw = get_gateway()
    gw.check()
    events = list(
        (await db.execute(select(Event).where(Event.project_id == project.id, Event.status != "archived"))).scalars()
    )
    registry: list[dict[str, Any]] = []
    current: dict[str, tuple[Event, list[dict[str, Any]]]] = {}
    for ev in events:
        versions = await service.versions_of(db, ev.id)
        base = service.latest_approved(versions) or (versions[0] if versions else None)
        params = base.params if base else []
        registry.append({"name": ev.name, "description": ev.description, "params": params})
        current[ev.name] = (ev, params)
    global_names = {g.name for g in await service.global_params(db, principal.org_id)}

    messages = prompts.tracking_messages(text, registry, sorted(global_names), app_version)
    res = await gw.chat(messages, temperature=0.1)
    try:
        data = prompts.parse_json_object(res.text)
    except ValueError:
        res = await gw.chat(
            [
                *messages,
                {"role": "assistant", "content": res.text},
                {"role": "user", "content": "Верни ответ строго одним JSON-объектом по схеме, без текста."},
            ],
            temperature=0,
        )
        try:
            data = prompts.parse_json_object(res.text)
        except ValueError as exc:
            raise UpstreamError("Модель не вернула разметку в формате JSON — попробуйте ещё раз") from exc

    draft = TrackingDraft(
        org_id=principal.org_id,
        project_id=project.id,
        title=title[:300],
        filename=filename[:300],
        app_version=app_version,
        source_text=text,
        truncated=truncated,
        summary=str(data.get("summary", ""))[:4000],
        model=res.model,
        created_by=principal.label,
    )
    db.add(draft)
    await db.flush()
    seen: set[str] = set()
    for i, raw in enumerate(data.get("events") or []):
        if not isinstance(raw, dict):
            continue
        name = snake(raw.get("name", ""))
        if not semver.NAME_RE.match(name) or name in seen:
            continue
        seen.add(name)
        warnings: list[str] = []
        proposed = clean_params(raw.get("params"), global_names, warnings)
        if name in current:
            ev, params = current[name]
            merged = merge_params(params, proposed)
            if semver.diff(params, merged).bump == "none":
                continue  # the registry already covers it
            action, event_id, final = "update", ev.id, merged
        else:
            if str(raw.get("action")) == "update":
                warnings.append("Модель предложила изменить событие, которого нет в реестре — будет создано новое")
            action, event_id, final = "create", None, proposed
        db.add(
            TrackingDraftItem(
                draft_id=draft.id,
                position=i,
                action=action,
                name=name,
                event_id=event_id,
                description=str(raw.get("description", ""))[:2000],
                category=snake(raw.get("category", ""))[:64],
                goal=str(raw.get("goal", ""))[:2000],
                question=str(raw.get("question", ""))[:2000],
                params=final,
                rationale=str(raw.get("rationale", ""))[:2000],
                quote=str(raw.get("quote", ""))[:2000],
                warnings=warnings,
            )
        )
    await db.flush()
    await ai_service.log(
        db,
        principal,
        "draft_events",
        project.id,
        question=title,
        answer=draft.summary,
        model=res.model,
        latency_ms=res.latency_ms,
        prompt_tokens=res.prompt_tokens,
        completion_tokens=res.completion_tokens,
    )
    return draft


async def get_draft(db: AsyncSession, principal: Principal, draft_id: uuid.UUID) -> TrackingDraft:
    d = await db.get(TrackingDraft, draft_id)
    if d is None or d.org_id != principal.org_id or not principal.can(P.EVENTS_VIEW, d.project_id):
        raise NotFoundError("Черновик разметки не найден")
    return d


async def items_of(db: AsyncSession, draft_id: uuid.UUID) -> list[TrackingDraftItem]:
    q = select(TrackingDraftItem).where(TrackingDraftItem.draft_id == draft_id).order_by(TrackingDraftItem.position)
    return list((await db.execute(q)).scalars())


async def _item(db: AsyncSession, draft: TrackingDraft, item_id: uuid.UUID) -> TrackingDraftItem:
    it = await db.get(TrackingDraftItem, item_id)
    if it is None or it.draft_id != draft.id:
        raise NotFoundError("Предложение не найдено")
    if it.status != "pending":
        raise ConflictError("Предложение уже рассмотрено")
    return it


async def update_item(
    db: AsyncSession, principal: Principal, draft: TrackingDraft, item_id: uuid.UUID, changes: dict[str, Any]
) -> TrackingDraftItem:
    principal.require(P.EVENTS_EDIT, draft.project_id)
    it = await _item(db, draft, item_id)
    if "name" in changes and it.action == "create":
        name = changes["name"]
        if not semver.NAME_RE.match(name):
            raise ValidationFailed("Имя события должно быть в snake_case, например offer_purchase")
    elif "name" in changes:
        changes.pop("name")  # an update targets an existing event
    if "params" in changes:
        changes["params"] = semver.normalize_params(changes["params"])
    for k, v in changes.items():
        setattr(it, k, v)
    return it


async def accept(db: AsyncSession, principal: Principal, draft: TrackingDraft, item_id: uuid.UUID) -> TrackingDraftItem:
    principal.require(P.EVENTS_EDIT, draft.project_id)
    it = await _item(db, draft, item_id)
    project = await db.get(Project, draft.project_id)
    assert project is not None
    changelog = f"Из документа «{draft.title}»" + (f": {it.rationale}" if it.rationale else "")
    if it.action == "create":
        if await db.scalar(select(Event.id).where(Event.project_id == project.id, Event.name == it.name)):
            raise ConflictError(f"Событие {it.name} уже есть в реестре — переименуйте предложение")
        ev, v = await service.create_event(
            db,
            principal,
            project,
            name=it.name,
            description=it.description,
            category=it.category,
            goal=it.goal,
            question=it.question,
            params=it.params,
            app_version=draft.app_version,
            tags=["ai-draft"],
        )
        v.changelog = changelog
        it.event_id = ev.id
    else:
        target = await db.get(Event, it.event_id) if it.event_id else None
        if target is None:
            raise NotFoundError("Событие для изменения не найдено")
        v = await service.propose_version(
            db, principal, target, it.params, changelog=changelog, app_version=draft.app_version
        )
    it.status, it.reviewed_by, it.result_version = "accepted", principal.label, v.version
    await db.flush()
    return it


async def reject(db: AsyncSession, principal: Principal, draft: TrackingDraft, item_id: uuid.UUID) -> TrackingDraftItem:
    principal.require(P.EVENTS_EDIT, draft.project_id)
    it = await _item(db, draft, item_id)
    it.status, it.reviewed_by = "rejected", principal.label
    return it
