"""AI use cases: answers over the knowledge base, text-to-SQL, drafts. Every call is logged with feedback."""

from __future__ import annotations

import time
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.errors import NotFoundError, PermissionDenied
from app.modules.ai import prompts, rag
from app.modules.ai.gateway import AiGateway, get_gateway
from app.modules.ai.models import AiInteraction
from app.modules.audit.service import record
from app.modules.connectors.models import CatalogTable, DataSource
from app.modules.connectors.service import pool
from app.modules.iam.models import Project
from app.modules.iam.permissions import P
from app.modules.iam.policy import Principal
from app.modules.query import service as query_service
from app.modules.query.guard import GuardError
from app.modules.semantic.models import Metric


def _user_id(principal: Principal) -> uuid.UUID | None:
    return principal.id if principal.kind == "user" else None


async def log(
    db: AsyncSession, principal: Principal, kind: str, project_id: uuid.UUID | None, **fields: Any
) -> AiInteraction:
    it = AiInteraction(org_id=principal.org_id, user_id=_user_id(principal), project_id=project_id, kind=kind, **fields)
    db.add(it)
    await db.flush()
    await record(
        db,
        f"ai.{kind}",
        principal=principal,
        resource_type="ai_interaction",
        resource_id=it.id,
        project_id=project_id,
        outcome="success" if it.status == "ok" else it.status,
        sql=it.sql or None,
        details={"model": it.model, "latency_ms": round(it.latency_ms)},
    )
    return it


# ---------------------------------------------------------------- knowledge base answers
def require_ask(principal: Principal, project_id: uuid.UUID | None) -> None:
    ok = principal.can(P.KB_ASK, project_id) if project_id else principal.can_anywhere(P.KB_ASK)
    if not ok:
        raise PermissionDenied("Недостаточно прав", details={"permission": P.KB_ASK})


async def prepare_ask(
    db: AsyncSession, principal: Principal, question: str, project_id: uuid.UUID | None, gw: AiGateway
) -> tuple[list[rag.Passage], list[dict[str, str]]]:
    require_ask(principal, project_id)
    gw.check()
    passages = await rag.retrieve(db, principal, question, project_id, gw)
    return passages, prompts.ask_messages(question, passages)


def sources_json(passages: list[rag.Passage]) -> list[dict[str, Any]]:
    return [
        {"n": i, "item_id": str(p.item_id), "title": p.title, "type": p.type, "score": round(p.score, 4)}
        for i, p in enumerate(passages, 1)
    ]


async def ask(db: AsyncSession, principal: Principal, question: str, project_id: uuid.UUID | None) -> AiInteraction:
    gw = get_gateway()
    passages, messages = await prepare_ask(db, principal, question, project_id, gw)
    res = await gw.chat(messages)
    return await log(
        db,
        principal,
        "ask",
        project_id,
        question=question,
        answer=res.text,
        sources=sources_json(passages),
        model=res.model,
        latency_ms=res.latency_ms,
        prompt_tokens=res.prompt_tokens,
        completion_tokens=res.completion_tokens,
    )


# ---------------------------------------------------------------- text-to-SQL
async def schema_docs(db: AsyncSession, source: DataSource) -> list[prompts.TableDoc]:
    tables = (
        await db.execute(
            select(CatalogTable)
            .where(CatalogTable.source_id == source.id, CatalogTable.present.is_(True))
            .options(selectinload(CatalogTable.columns))
            .order_by(CatalogTable.schema_name, CatalogTable.name)
        )
    ).scalars()
    docs = []
    for t in tables:
        cols = [
            (c.name, c.data_type, (c.description or c.source_comment) + (" (PII)" if c.is_pii else ""))
            for c in sorted(t.columns, key=lambda c: c.ordinal)
            if c.present
        ]
        docs.append(prompts.TableDoc(t.name, cols, t.description or t.source_comment))
    return docs


async def metric_docs(db: AsyncSession, org_id: uuid.UUID) -> list[str]:
    rows = (await db.execute(select(Metric).where(Metric.org_id == org_id).order_by(Metric.key))).scalars()
    return [
        f"{m.key} — {m.name}: {m.expression} FROM {m.table}" + (f" WHERE {m.filters}" if m.filters else "")
        for m in rows
    ]


async def generate_sql(
    db: AsyncSession, principal: Principal, project: Project, source: DataSource, question: str
) -> tuple[AiInteraction, bool, str]:
    """Returns (interaction, valid, error). The SQL is only proposed: running it is a separate, guarded action."""
    principal.require(P.AI_SQL, project.id)
    query_service.check_sql_access(principal, source, project)
    gw = get_gateway()
    gw.check()
    dialect = (await pool.get(source)).dialect
    tables = await schema_docs(db, source)
    examples = prompts.select_examples(question, prompts.load_golden(), {t.name.lower() for t in tables})
    messages = prompts.sql_messages(question, dialect, tables, examples, await metric_docs(db, principal.org_id))
    model = gw.s.ai_sql_model or gw.s.ai_chat_model
    started = time.perf_counter()
    res = await gw.chat(messages, model=model, temperature=0)
    sql, explanation = prompts.extract_sql(res.text)
    tokens = [res.prompt_tokens, res.completion_tokens]
    valid, error = True, ""
    for attempt in range(2):
        try:
            await query_service.validate(db, principal, source, project, sql)
            valid, error = True, ""
            break
        except GuardError as exc:
            valid, error = False, exc.message
            if attempt == 1:
                break
            fix = await gw.chat(
                [*messages, {"role": "assistant", "content": res.text}, prompts.repair_message(sql, error)],
                model=model,
                temperature=0,
            )
            res = fix
            sql, explanation = prompts.extract_sql(fix.text)
            tokens = [tokens[0] + fix.prompt_tokens, tokens[1] + fix.completion_tokens]
    it = await log(
        db,
        principal,
        "sql",
        project.id,
        question=question,
        answer=explanation,
        sql=sql,
        sources=[{"example": e.id} for e in examples],
        model=res.model,
        latency_ms=(time.perf_counter() - started) * 1000,
        prompt_tokens=tokens[0],
        completion_tokens=tokens[1],
        status="ok" if valid else "rejected",
        error=error,
    )
    return it, valid, error


# ---------------------------------------------------------------- drafts
def _brief_result(result: dict[str, Any]) -> dict[str, Any]:
    """Only aggregates go to the model: group sizes, means, lifts, probabilities, SRM."""

    def metric(m: dict[str, Any]) -> dict[str, Any]:
        return {
            "metric": m["name"],
            "variants": [{"key": v["key"], "n": v["n"], "mean": round(v["mean"], 5)} for v in m["variants"]],
            "comparisons": [
                {
                    "variant": c["variant"],
                    "prob_better": round(c["prob_better"], 4),
                    "lift": round(c["lift"], 4),
                    "lift_ci": [round(x, 4) for x in c["lift_ci"]],
                    "p_value": round(c["frequentist"]["p_value"], 5) if c.get("frequentist") else None,
                }
                for c in m["comparisons"]
            ],
        }

    return {
        "primary": metric(result["primary"]),
        "secondary": [metric(m) for m in result.get("secondary", [])],
        "srm": {"p_value": result["srm"]["p_value"], "mismatch": result["srm"]["mismatch"]},
        "segments": [
            {
                "segment": f"{s['segment']}={s['value']}",
                "n": sum(v["n"] for v in s["variants"]),
                "prob_better": s["comparisons"][0]["prob_better"] if s["comparisons"] else None,
                "lift": s["comparisons"][0]["lift"] if s["comparisons"] else None,
            }
            for s in result.get("segments", [])[:12]
        ],
        "recommendation": result.get("recommendation"),
    }


async def draft_experiment(db: AsyncSession, principal: Principal, experiment_id: uuid.UUID) -> AiInteraction:
    from app.modules.experiments.service import get_experiment

    exp = await get_experiment(db, principal, experiment_id)
    if not (principal.can(P.EXPERIMENTS_EDIT, exp.project_id) or principal.can(P.EXPERIMENTS_APPROVE, exp.project_id)):
        raise PermissionDenied("Недостаточно прав", details={"permission": P.EXPERIMENTS_EDIT})
    if not exp.last_result:
        raise NotFoundError("Результаты эксперимента ещё не рассчитаны")
    design = {
        "name": exp.name,
        "hypothesis": exp.hypothesis,
        "metric": exp.metric_key,
        "threshold": exp.threshold,
        "mde": exp.mde,
        "variants": exp.variants,
        "planned_users": exp.planned_users,
    }
    gw = get_gateway()
    res = await gw.chat(prompts.experiment_messages(design, _brief_result(exp.last_result)))
    return await log(
        db,
        principal,
        "draft_experiment",
        exp.project_id,
        question=exp.key,
        answer=res.text,
        model=res.model,
        latency_ms=res.latency_ms,
        prompt_tokens=res.prompt_tokens,
        completion_tokens=res.completion_tokens,
    )


async def draft_widget(
    db: AsyncSession,
    principal: Principal,
    project_id: uuid.UUID | None,
    title: str,
    columns: list[str],
    rows: list[list[Any]],
) -> AiInteraction:
    ok = principal.can(P.DASHBOARDS_VIEW, project_id) if project_id else principal.can_anywhere(P.DASHBOARDS_VIEW)
    if not ok:
        raise PermissionDenied("Недостаточно прав", details={"permission": P.DASHBOARDS_VIEW})
    gw = get_gateway()
    res = await gw.chat(prompts.widget_messages(title, columns, rows))
    return await log(
        db,
        principal,
        "draft_widget",
        project_id,
        question=title,
        answer=res.text,
        model=res.model,
        latency_ms=res.latency_ms,
        prompt_tokens=res.prompt_tokens,
        completion_tokens=res.completion_tokens,
    )


async def feedback(
    db: AsyncSession, principal: Principal, interaction_id: uuid.UUID, rating: int, comment: str
) -> AiInteraction:
    it = await db.get(AiInteraction, interaction_id)
    if it is None or it.org_id != principal.org_id or it.user_id != _user_id(principal):
        raise NotFoundError("Ответ не найден")
    it.rating, it.feedback = rating, comment
    return it


async def index_all(db: AsyncSession) -> int:
    """Beat job: chunks (and embeds, when configured) new or changed knowledge-base records."""
    gw = get_gateway()
    return await rag.index_pending(db, gw if gw.enabled else None)
