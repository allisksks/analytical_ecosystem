"""Background workers (TZ: Celery + schedule): post-release validation, experiment recalculation.

celery -A app.worker worker -B --loglevel=INFO
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from celery import Celery

from app.core.config import get_settings
from app.core.db import dispose_engine, get_sessionmaker
from app.core.logging import configure_logging

settings = get_settings()
configure_logging(settings.log_level, settings.log_json)
broker = settings.redis_url or "memory://"
celery_app = Celery("analytics", broker=broker, backend=None)
celery_app.conf.update(
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_time_limit=1800,
    timezone="UTC",
    beat_schedule={
        "ems-validation": {"task": "ems.validate_all", "schedule": settings.validation_interval_min * 60},
        "experiments-recalc": {
            "task": "experiments.recalculate_all",
            "schedule": settings.experiments_interval_min * 60,
        },
        "ai-index-kb": {"task": "ai.index_kb", "schedule": 15 * 60},
    },
)


def _run(fn: Callable[[Any], Awaitable[int]]) -> int:
    async def main() -> int:
        try:
            async with get_sessionmaker()() as db:
                return await fn(db)
        finally:
            await dispose_engine()

    return asyncio.run(main())


@celery_app.task(name="ems.validate_all")
def validate_all() -> int:
    from app.modules.ems.validation import validate_all as job

    return _run(job)


@celery_app.task(name="experiments.recalculate_all")
def recalculate_all() -> int:
    from app.modules.experiments.service import recalculate_all as job

    return _run(job)


@celery_app.task(name="ai.index_kb")
def index_kb() -> int:
    """Chunks new/changed knowledge-base records and embeds them when an embedding model is configured."""
    from app.modules.ai.service import index_all

    async def job(db: Any) -> int:
        n = await index_all(db)
        await db.commit()
        return n

    return _run(job)
