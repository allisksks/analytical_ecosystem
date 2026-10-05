"""Migrations must apply on an empty database and roll back cleanly (TZ: updates with rollback)."""

from __future__ import annotations

import asyncio

from tests.conftest import TEST_DB_URL, _recreate_database


async def test_upgrade_downgrade_upgrade() -> None:
    from alembic import command
    from alembic.config import Config

    from tests.conftest import BACKEND_DIR

    url = TEST_DB_URL.rsplit("/", 1)[0] + "/platform_migrations"
    await _recreate_database(url)
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    cfg.attributes["database_url"] = url
    cfg.attributes["configure_logger"] = False

    def roundtrip() -> None:
        command.upgrade(cfg, "head")
        command.downgrade(cfg, "base")
        command.upgrade(cfg, "head")
        command.check(cfg)  # models and migrations are in sync (no forgotten autogenerate)

    await asyncio.to_thread(roundtrip)
