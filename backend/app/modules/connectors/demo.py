"""Demo content: the bundled mobile-game dataset as a data source with a curated catalog."""

from __future__ import annotations

import asyncio
from pathlib import Path

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.modules.connectors.models import DataSource
from app.modules.connectors.service import refresh_catalog
from app.modules.iam.demo_hooks import demo_hook
from app.modules.iam.models import Organization, Project, User

log = structlog.get_logger("demo")

TABLE_DOCS: dict[str, str] = {
    "events": "Сырые события клиентов игр (одна строка — одно событие). params — JSON с параметрами события.",
    "users": "Установки: одна строка на пользователя, атрибуты установки и стоимость привлечения (cpi_usd).",
    "payments": "Покупки в приложении, revenue_usd — за вычетом комиссии стора.",
    "ad_revenue": "Доход от рекламы по пользователю, дню и сети.",
    "ab_assignments": "Назначения пользователей в группы A/B-экспериментов.",
    "mart_retention": "Витрина удержания: строка на пользователя и день активности; day_n — день жизни от установки.",
    "mart_monetisation": "Витрина монетизации по дням, платформам, странам и источникам: DAU, платящие, доход.",
    "mart_portfolio": "Портфельная витрина: ключевые метрики каждой игры по дням (DAU, установки, доход, D1/D7).",
    "mart_ua": "Витрина привлечения: установки, расходы и доход первой недели по источникам и кампаниям.",
}
COLUMN_DOCS: dict[str, str] = {
    "app_id": "Идентификатор игры (проекта)",
    "user_id": "Внутренний идентификатор игрока",
    "device_id": "Идентификатор устройства — персональные данные",
    "install_date": "Дата установки",
    "day_n": "День жизни игрока от установки (0 — день установки)",
    "platform": "ios | android",
    "country": "Страна, ISO-3166 alpha-2",
    "source": "Источник трафика (organic или рекламная сеть)",
    "revenue_usd": "Доход в долларах США",
    "dau": "Активные пользователи за день",
}


@demo_hook
async def demo_source(db: AsyncSession, org: Organization, projects: dict[str, Project], admin: User) -> None:
    path = await asyncio.to_thread(Path(get_settings().demo_data_dir).resolve)
    if not await asyncio.to_thread((path / "events.parquet").exists):
        log.warning("demo data not found, skipping demo source", path=str(path))
        return
    source = DataSource(
        org_id=org.id,
        name="Демо: мобильные игры (Parquet)",
        type="files",
        config={"path": str(path)},
        is_demo=True,
        created_by=admin.id,
        status="ok",
    )
    db.add(source)
    await db.flush()
    await refresh_catalog(db, source)
    await db.refresh(source, attribute_names=["tables"])
    for table in source.tables:
        table.description = TABLE_DOCS.get(table.name, "")
        table.owner = "data-team"
        for col in table.columns:
            col.description = COLUMN_DOCS.get(col.name, "")
    log.info("demo source created", tables=len(source.tables))
