"""Demo: the two experiments present in the demo data (calculated and decided), plus a few in design/review."""

from __future__ import annotations

from datetime import UTC, datetime, time
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.connectors.models import DataSource
from app.modules.experiments import service
from app.modules.iam.demo_hooks import demo_hook_late
from app.modules.iam.models import Organization, Project, User
from app.modules.iam.service import system_principal
from app.modules.kb.models import KnowledgeItem

log = structlog.get_logger("demo")

DONE: list[dict[str, Any]] = [
    {
        "key": "tutorial_v2",
        "name": "Iron Shells · Новый туториал (tutorial_v2)",
        "hypothesis": "Если сократить туториал с 9 до 5 шагов и дать первый бой раньше, Retention D7 вырастет, "
        "потому что новички быстрее доходят до основного геймплея.",
        "metric_key": "retention_d7",
        "secondary_metrics": ["retention_d1", "active_days_d7"],
        "segments": ["platform", "source"],
        "mde": 0.08,
        "event_name": "tutorial_step",
        "owner": "A. Volkova",
        "decision": "ship",
        "conclusion": "Новый туториал поднимает Retention D7 примерно на 2 п.п. без ухудшения защитных метрик. "
        "Решение — раскатить на 100% игроков.",
        "kb_title": "Iron Shells · Новый туториал (tutorial_v2)",
    },
    {
        "key": "starter_pack_price",
        "name": "Iron Shells · Стартовый набор $4.99 → $5.99",
        "hypothesis": "Если поднять цену стартового набора на $1, ARPU вырастет, потому что спрос на набор неэластичен.",
        "metric_key": "arpu_d7",
        "secondary_metrics": ["conversion_d7"],
        "segments": ["platform", "country"],
        "mde": 0.05,
        "event_name": "iap_purchase",
        "owner": "P. Orlov",
        "decision": "keep_control",
        "conclusion": "Конверсия в платёж упала, ARPU D7 не вырос. Оставляем $4.99.",
        "kb_title": "Iron Shells · Стартовый набор $4.99 → $5.99",
    },
]
PLANNED: list[tuple[str, str, dict[str, Any]]] = [
    (
        "bloom_merge",
        "review",
        {
            "key": "daily_quest_4",
            "name": "Bloom & Merge · Четвёртый ежедневный квест",
            "hypothesis": "Дополнительный квест увеличит число активных дней за первую неделю.",
            "metric_key": "active_days_d7",
            "secondary_metrics": ["retention_d7"],
            "segments": ["platform"],
            "mde": 0.05,
            "planned_users": 24000,
            "planned_days": 21,
            "owner": "M. Sokolov",
            "splitter": "internal",
        },
    ),
    (
        "iron_shells",
        "draft",
        {
            "key": "shop_offer_layout",
            "name": "Iron Shells · Персональное предложение на главном экране",
            "hypothesis": "Если показать оффер в первый день, конверсия в платёж D7 вырастет на 10%.",
            "metric_key": "conversion_d7",
            "secondary_metrics": ["retention_d7"],
            "segments": ["platform", "country"],
            "mde": 0.1,
            "event_name": "iap_purchase",
            "splitter": "internal",
            "traffic_share": 0.5,
        },
    ),
]


@demo_hook_late
async def demo_experiments(db: AsyncSession, org: Organization, projects: dict[str, Project], admin: User) -> None:
    source = (
        await db.execute(select(DataSource).where(DataSource.org_id == org.id, DataSource.is_demo.is_(True)))
    ).scalar_one_or_none()
    iron = projects.get("iron_shells")
    if source is None or iron is None:
        return
    principal = system_principal(org.id, "starter-kit")
    for spec in DONE:
        data = {k: v for k, v in spec.items() if k not in ("decision", "conclusion", "kb_title")}
        exp = await service.create(
            db,
            principal,
            iron,
            {
                **data,
                "source_id": source.id,
                "variants": [
                    {"key": "A", "name": "Контроль", "weight": 0.5},
                    {"key": "B", "name": "Тест", "weight": 0.5},
                ],
            },
        )
        exp.status, exp.approved_by = "running", "M. Lead"
        try:
            result = await service.calculate(db, principal, exp)
        except Exception as exc:  # demo data without this experiment: leave it running without results
            log.warning("demo experiment not calculated", key=exp.key, error=str(exc))
            continue
        exp.planned_users = result.matured_users
        if result.first_assigned_at and result.last_assigned_at:
            exp.started_at = result.first_assigned_at.replace(tzinfo=UTC)
            exp.ended_at = datetime.combine(result.last_assigned_at.date(), time(23, 59), UTC)
            exp.planned_days = (exp.ended_at - exp.started_at).days + 1
        exp.status, exp.decision, exp.conclusion, exp.decided_by = (
            "completed",
            spec["decision"],
            spec["conclusion"],
            "M. Lead",
        )
        exp.kb_item_id = await db.scalar(
            select(KnowledgeItem.id).where(KnowledgeItem.org_id == org.id, KnowledgeItem.title == spec["kb_title"])
        )
    for project_key, status, spec in PLANNED:
        project = projects.get(project_key)
        if project is None:
            continue
        exp = await service.create(db, principal, project, {**spec, "source_id": source.id})
        exp.status = status
    await db.flush()
    log.info("demo experiments created")
