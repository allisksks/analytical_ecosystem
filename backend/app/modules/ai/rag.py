"""Retrieval over the knowledge base: chunking, indexing and hybrid (full-text + vector) search.

Only records the principal may read are ever retrieved, so the assistant cannot leak a project's knowledge.
Without an embedding model the search degrades gracefully to PostgreSQL full-text search.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass

import structlog
from sqlalchemy import and_, delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.ai.gateway import AiGateway
from app.modules.ai.models import KbChunk
from app.modules.iam.policy import Principal
from app.modules.kb.models import KnowledgeItem
from app.modules.kb.service import _match, _tsquery, visibility

log = structlog.get_logger("ai")
CHUNK_CHARS = 900
RRF_K = 60


@dataclass
class Passage:
    item_id: uuid.UUID
    title: str
    type: str
    project_id: uuid.UUID | None
    text: str
    score: float = 0.0


def chunk_item(item: KnowledgeItem) -> list[str]:
    """Splits Markdown by headings/paragraphs into ~900-char passages, each prefixed with the record title."""
    head = f"{item.title}\n{item.summary}".strip()
    blocks = [b.strip() for b in re.split(r"\n(?=#{1,6} )|\n{2,}", item.body or "") if b.strip()]
    chunks: list[str] = []
    cur = ""
    for b in blocks:
        if cur and len(cur) + len(b) > CHUNK_CHARS:
            chunks.append(cur)
            cur = ""
        cur = f"{cur}\n\n{b}" if cur else b
        while len(cur) > CHUNK_CHARS * 1.5:
            chunks.append(cur[:CHUNK_CHARS])
            cur = cur[CHUNK_CHARS:]
    if cur:
        chunks.append(cur)
    return [f"{head}\n\n{c}" for c in chunks] or [head]


async def index_item(db: AsyncSession, item: KnowledgeItem, gw: AiGateway | None) -> int:
    texts = chunk_item(item)
    vectors: list[list[float]] | None = None
    model = ""
    if gw is not None and gw.enabled and gw.s.ai_embedding_model:
        try:
            vectors = await gw.embed(texts)
            model = gw.s.ai_embedding_model
        except Exception as exc:  # index text anyway; embeddings are retried on the next pass
            log.warning("embedding failed", item=str(item.id), error=getattr(exc, "message", str(exc)))
    await db.execute(delete(KbChunk).where(KbChunk.item_id == item.id))
    for i, text in enumerate(texts):
        db.add(
            KbChunk(
                item_id=item.id,
                item_version=item.version,
                chunk_no=i,
                text=text,
                embedding_model=model,
                embedding=vectors[i] if vectors else None,
            )
        )
    await db.flush()
    return len(texts)


async def index_pending(db: AsyncSession, gw: AiGateway | None, limit: int = 500) -> int:
    """(Re)indexes records whose text changed or that lack embeddings of the current model."""
    model = gw.s.ai_embedding_model if gw is not None and gw.enabled else None
    current = select(KbChunk.item_id).where(
        KbChunk.item_id == KnowledgeItem.id,
        KbChunk.item_version == KnowledgeItem.version,
        *([KbChunk.embedding_model == model] if model else []),
    )
    items = list(
        (
            await db.execute(
                select(KnowledgeItem).where(KnowledgeItem.status != "archived", ~current.exists()).limit(limit)
            )
        ).scalars()
    )
    for item in items:
        await index_item(db, item, gw)
    return len(items)


def _visible_items(principal: Principal, project_id: uuid.UUID | None) -> list[object]:
    conds: list[object] = [visibility(principal), KnowledgeItem.status == "published"]
    if project_id is not None:
        conds.append(or_(KnowledgeItem.project_id == project_id, KnowledgeItem.project_id.is_(None)))
    return conds


async def retrieve(
    db: AsyncSession,
    principal: Principal,
    question: str,
    project_id: uuid.UUID | None,
    gw: AiGateway | None,
    k: int = 6,
) -> list[Passage]:
    conds = _visible_items(principal, project_id)
    ranks: dict[uuid.UUID, float] = {}
    passages: dict[uuid.UUID, Passage] = {}

    def add(rows: list[tuple[KbChunk, KnowledgeItem]], weight: float = 1.0) -> None:
        for rank, (ch, item) in enumerate(rows):
            ranks[ch.id] = ranks.get(ch.id, 0.0) + weight / (RRF_K + rank + 1)
            passages[ch.id] = Passage(item.id, item.title, item.type, item.project_id, ch.text)

    # lexical: chunks of matching records ranked by full-text rank of the passage itself
    tsq = _tsquery(question)
    lexical = (
        await db.execute(
            select(KbChunk, KnowledgeItem)
            .join(KnowledgeItem, KnowledgeItem.id == KbChunk.item_id)
            .where(and_(*conds), _match(question))  # type: ignore[arg-type]
            .order_by(func.ts_rank_cd(func.to_tsvector("russian", KbChunk.text), tsq).desc())
            .limit(k * 3)
        )
    ).all()
    add([(c, i) for c, i in lexical])
    # semantic
    if gw is not None and gw.enabled and gw.s.ai_embedding_model:
        try:
            [vec] = await gw.embed([question])
            dist = KbChunk.embedding.cosine_distance(vec)
            semantic = (
                await db.execute(
                    select(KbChunk, KnowledgeItem)
                    .join(KnowledgeItem, KnowledgeItem.id == KbChunk.item_id)
                    .where(
                        and_(*conds),  # type: ignore[arg-type]
                        KbChunk.embedding_model == gw.s.ai_embedding_model,
                        func.vector_dims(KbChunk.embedding) == len(vec),
                    )
                    .order_by(dist)
                    .limit(k * 3)
                )
            ).all()
            add([(c, i) for c, i in semantic], weight=1.2)
        except Exception as exc:
            log.warning("semantic search failed", error=getattr(exc, "message", str(exc)))
    if not passages:  # records not indexed yet: fall back to whole records
        items = (
            await db.execute(select(KnowledgeItem).where(and_(*conds), _match(question)).limit(k))  # type: ignore[arg-type]
        ).scalars()
        return [
            Passage(i.id, i.title, i.type, i.project_id, f"{i.title}\n{i.summary}\n\n{i.body}"[: CHUNK_CHARS * 2])
            for i in items
        ]
    best = sorted(ranks, key=lambda cid: -ranks[cid])
    out: list[Passage] = []
    per_item: dict[uuid.UUID, int] = {}
    for cid in best:
        p = passages[cid]
        if per_item.get(p.item_id, 0) >= 2:  # diversity: at most two passages per record
            continue
        per_item[p.item_id] = per_item.get(p.item_id, 0) + 1
        p.score = ranks[cid]
        out.append(p)
        if len(out) >= k:
            break
    return out
