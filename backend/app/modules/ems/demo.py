"""Demo: event registry of the three games built from actual demo data, approved, plus a first validation."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.connectors.models import DataSource
from app.modules.ems import service
from app.modules.ems.models import EventVersion, GlobalParam, TrackingConfig
from app.modules.ems.validation import run_validation
from app.modules.iam.demo_hooks import demo_hook
from app.modules.iam.models import Organization, Project, User
from app.modules.iam.service import system_principal
from app.modules.query import service as query_service

log = structlog.get_logger("demo")

GLOBAL = [
    ("user_id", "string", True, "Идентификатор игрока"),
    ("device_id", "string", True, "Идентификатор устройства (персональные данные)"),
    ("session_id", "string", True, "Идентификатор сессии"),
    ("platform", "enum", True, "ios | android"),
    ("app_version", "string", True, "Версия сборки (semver)"),
    ("country", "string", True, "ISO-3166 alpha-2"),
    ("source", "string", True, "Источник установки"),
    ("event_ts", "timestamp", True, "Время события на сервере"),
]
DOCS: dict[str, tuple[str, str, list[str], str]] = {
    # name: (description, category, metrics, question)
    "session_start": (
        "Старт игровой сессии",
        "core",
        ["sessions_per_user", "dau"],
        "Как часто игроки возвращаются в течение дня?",
    ),
    "tutorial_step": (
        "Шаг обучения пройден",
        "onboarding",
        ["retention_d1"],
        "На каком шаге обучения теряем новичков?",
    ),
    "level_start": ("Старт уровня", "progression", [], "Как быстро игроки проходят контент?"),
    "level_complete": ("Уровень пройден", "progression", [], "Не слишком ли сложны уровни?"),
    "match_start": ("Начало боя (PvE/PvP)", "gameplay", [], "Какие режимы популярнее?"),
    "chest_open": ("Открытие сундука", "economy", [], "Как работает экономика наград?"),
    "iap_purchase": (
        "Покупка в приложении",
        "monetisation",
        ["revenue", "arppu", "payer_conversion"],
        "Сколько и что покупают?",
    ),
    "ad_impression": ("Показ рекламы", "monetisation", ["ad_revenue"], "Сколько рекламы видит игрок?"),
}


@demo_hook
async def demo_events(db: AsyncSession, org: Organization, projects: dict[str, Project], admin: User) -> None:
    source = (
        await db.execute(select(DataSource).where(DataSource.org_id == org.id, DataSource.is_demo.is_(True)))
    ).scalar_one_or_none()
    if source is None:
        return
    for name, typ, req, desc in GLOBAL:
        db.add(
            GlobalParam(
                org_id=org.id,
                name=name,
                type=typ,
                required=req,
                description=desc,
                enum=["ios", "android"] if name == "platform" else [],
            )
        )
    principal = system_principal(org.id, "starter-kit")
    for project in projects.values():
        db.add(TrackingConfig(project_id=project.id, source_id=source.id))
        await db.flush()
        out = await query_service.execute(
            db,
            principal,
            source,
            project,
            "SELECT event_name, params FROM events WHERE event_date >= (SELECT max(event_date) - 2 FROM events)",
            origin="ems",
            limit=60_000,
        )
        samples: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for name, raw in out.rows:
            if len(samples[name]) < 500:
                samples[name].append(service.parse_params(raw))
        for name, rows in sorted(samples.items()):
            desc, category, metrics, question = DOCS.get(name, ("", "", [], ""))
            ev, v = await service.create_event(
                db,
                principal,
                project,
                name=name,
                description=desc,
                category=category,
                owner="A. Volkova",
                goal="Понимать поведение игроков",
                question=question,
                metric_keys=metrics,
                params=service.infer_params(rows),
                app_version="1.6.0",
            )
            v.status, v.reviewed_by = "approved", "M. Lead"
            ev.current_version, ev.status = v.version, "active"
        await db.flush()
    # a pending change for the review queue
    iron = projects.get("iron_shells")
    if iron:
        from app.modules.ems.models import Event

        ev = (
            await db.execute(select(Event).where(Event.project_id == iron.id, Event.name == "level_complete"))
        ).scalar_one()
        v = (await db.execute(select(EventVersion).where(EventVersion.event_id == ev.id))).scalar_one()
        await service.propose_version(
            db,
            principal,
            ev,
            [*v.params, {"name": "stars", "type": "int", "required": False, "description": "Звёзды за уровень (0–3)"}],
            changelog="Добавлены звёзды за уровень",
            app_version="1.9.0",
        )
        await db.flush()
        await run_validation(db, iron)
    log.info("demo events registered")
