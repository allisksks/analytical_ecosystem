"""AI assistant API. Answers stream as Server-Sent Events: ``sources`` → ``delta``… → ``done`` (or ``error``)."""

from __future__ import annotations

import json
import time
import uuid
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select

from app.core.db import get_sessionmaker
from app.modules.ai import rag, service
from app.modules.ai.gateway import get_gateway
from app.modules.ai.models import AiInteraction, KbChunk
from app.modules.ai.schemas import (
    AiStatus,
    AskIn,
    AskOut,
    DraftOut,
    FeedbackIn,
    InteractionOut,
    Source,
    SqlIn,
    SqlOut,
    WidgetDraftIn,
)
from app.modules.connectors.service import get_source
from app.modules.iam.deps import DB, CurrentPrincipal, require
from app.modules.iam.permissions import P
from app.modules.iam.policy import Principal
from app.modules.kb.models import KnowledgeItem
from app.modules.query.service import load_project

router = APIRouter(prefix="/ai", tags=["ai"])
Auditor = Annotated[Principal, Depends(require(P.ADMIN_AUDIT))]
Moderator = Annotated[Principal, Depends(require(P.KB_MODERATE))]


@router.get("/status", response_model=AiStatus, summary="Is the assistant configured (and reachable)?")
async def status(principal: CurrentPrincipal, db: DB, check: bool = False) -> AiStatus:
    gw = get_gateway()
    s = gw.s
    indexed = await db.scalar(select(func.count(func.distinct(KbChunk.item_id)))) or 0
    total = (
        await db.scalar(select(func.count()).select_from(KnowledgeItem).where(KnowledgeItem.org_id == principal.org_id))
        or 0
    )
    out = AiStatus(
        enabled=s.ai_enabled,
        cloud=gw.cloud,
        allow_cloud=s.ai_allow_cloud,
        chat_model=s.ai_chat_model,
        sql_model=s.ai_sql_model or s.ai_chat_model,
        embedding_model=s.ai_embedding_model,
        indexed_items=indexed,
        total_items=total,
    )
    if check and s.ai_enabled:
        out.reachable, out.error = await gw.ping()
    return out


@router.post("/ask", response_model=AskOut, summary="Answer from the knowledge base (non-streaming)")
async def ask(body: AskIn, principal: CurrentPrincipal, db: DB) -> AskOut:
    await load_project(db, principal, body.project_id)
    it = await service.ask(db, principal, body.question, body.project_id)
    return AskOut(
        interaction_id=it.id,
        answer=it.answer,
        sources=[Source(**s) for s in it.sources],
        model=it.model,
        latency_ms=it.latency_ms,
    )


def _sse(event: str, data: object) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@router.post("/ask/stream", summary="Answer from the knowledge base as Server-Sent Events")
async def ask_stream(body: AskIn, principal: CurrentPrincipal, db: DB) -> StreamingResponse:
    await load_project(db, principal, body.project_id)
    gw = get_gateway()
    passages, messages = await service.prepare_ask(db, principal, body.question, body.project_id, gw)
    sources = service.sources_json(passages)

    async def events() -> AsyncIterator[str]:
        yield _sse("sources", sources)
        started, parts, error = time.perf_counter(), [], ""
        try:
            async for delta in gw.stream(messages):
                parts.append(delta)
                yield _sse("delta", delta)
        except Exception as exc:
            error = getattr(exc, "message", None) or str(exc)
            yield _sse("error", {"message": error})
        # the request session is closed while streaming: log with a session of our own
        async with get_sessionmaker()() as s:
            it = await service.log(
                s,
                principal,
                "ask",
                body.project_id,
                question=body.question,
                answer="".join(parts).strip(),
                sources=sources,
                model=gw.s.ai_chat_model,
                latency_ms=(time.perf_counter() - started) * 1000,
                status="error" if error else "ok",
                error=error,
            )
            await s.commit()
            yield _sse("done", {"interaction_id": str(it.id)})

    return StreamingResponse(
        events(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
    )


@router.post("/sql", response_model=SqlOut, summary="Generate SQL for a question (validated, not executed)")
async def generate_sql(body: SqlIn, principal: CurrentPrincipal, db: DB) -> SqlOut:
    project = await load_project(db, principal, body.project_id)
    assert project is not None
    source = await get_source(db, principal, body.source_id)
    it, valid, error = await service.generate_sql(db, principal, project, source, body.question)
    return SqlOut(
        interaction_id=it.id,
        sql=it.sql,
        explanation=it.answer,
        valid=valid,
        error=error,
        examples=[s["example"] for s in it.sources],
        model=it.model,
        latency_ms=it.latency_ms,
    )


@router.post("/draft/experiment/{experiment_id}", response_model=DraftOut, summary="Draft of an experiment conclusion")
async def draft_experiment(experiment_id: uuid.UUID, principal: CurrentPrincipal, db: DB) -> DraftOut:
    it = await service.draft_experiment(db, principal, experiment_id)
    return DraftOut(interaction_id=it.id, text=it.answer, model=it.model, latency_ms=it.latency_ms)


@router.post("/draft/widget", response_model=DraftOut, summary="Observations on a widget's data")
async def draft_widget(body: WidgetDraftIn, principal: CurrentPrincipal, db: DB) -> DraftOut:
    await load_project(db, principal, body.project_id)
    it = await service.draft_widget(db, principal, body.project_id, body.title, body.columns, body.rows)
    return DraftOut(interaction_id=it.id, text=it.answer, model=it.model, latency_ms=it.latency_ms)


@router.post("/interactions/{interaction_id}/feedback", response_model=InteractionOut)
async def feedback(interaction_id: uuid.UUID, body: FeedbackIn, principal: CurrentPrincipal, db: DB) -> AiInteraction:
    return await service.feedback(db, principal, interaction_id, body.rating, body.comment)


@router.get("/interactions", response_model=list[InteractionOut], summary="Answer log for quality review")
async def interactions(
    db: DB,
    principal: Auditor,
    kind: str | None = None,
    rating: int | None = None,
    limit: int = Query(100, le=500),
) -> list[AiInteraction]:
    q = select(AiInteraction).where(AiInteraction.org_id == principal.org_id)
    if kind:
        q = q.where(AiInteraction.kind == kind)
    if rating is not None:
        q = q.where(AiInteraction.rating == rating)
    return list((await db.execute(q.order_by(AiInteraction.created_at.desc()).limit(limit))).scalars())


@router.post("/reindex", summary="Index the knowledge base for the assistant now")
async def reindex(db: DB, _: Moderator) -> dict[str, int]:
    gw = get_gateway()
    return {"indexed": await rag.index_pending(db, gw if gw.enabled else None, limit=5000)}
