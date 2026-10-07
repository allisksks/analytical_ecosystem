from __future__ import annotations

from app.worker import celery_app


def test_beat_schedule_and_tasks_are_registered() -> None:
    assert {"ems-validation", "experiments-recalc", "ai-index-kb"} <= set(celery_app.conf.beat_schedule)
    assert "ems.validate_all" in celery_app.tasks
    assert "experiments.recalculate_all" in celery_app.tasks
    assert "ai.index_kb" in celery_app.tasks
