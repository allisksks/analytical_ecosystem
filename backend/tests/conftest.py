"""Shared fixtures.

Tests run against a real PostgreSQL (with pgvector) — the same engine as production.
Point ``TEST_DATABASE_URL`` to a server where the user may create databases; by default
``postgresql+asyncpg://postgres:pg@localhost:55432/platform_test`` (see Makefile ``test-db``).
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from pathlib import Path

import asyncpg
import pytest
from sqlalchemy.engine import make_url

TEST_DB_URL = os.environ.get("TEST_DATABASE_URL", "postgresql+asyncpg://postgres:pg@localhost:55432/platform_test")
os.environ["DATABASE_URL"] = TEST_DB_URL
os.environ.setdefault("ENV", "test")
os.environ.setdefault("REDIS_URL", "")
os.environ.setdefault("SECRET_KEY", "test-secret-key-test-secret-key-0123456789")
os.environ.setdefault("AI_ENABLED", "false")

BACKEND_DIR = Path(__file__).resolve().parents[1]


async def _recreate_database(url: str) -> None:
    u = make_url(url)
    admin_dsn = f"postgresql://{u.username}:{u.password}@{u.host}:{u.port}/postgres"
    conn = await asyncpg.connect(admin_dsn)
    try:
        await conn.execute(f'DROP DATABASE IF EXISTS "{u.database}" WITH (FORCE)')
        await conn.execute(f'CREATE DATABASE "{u.database}"')
    finally:
        await conn.close()


def _alembic_upgrade(url: str) -> None:
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    cfg.attributes["database_url"] = url
    cfg.attributes["configure_logger"] = False
    command.upgrade(cfg, "head")


@pytest.fixture(scope="session", autouse=True)
async def _database() -> AsyncIterator[None]:
    await _recreate_database(TEST_DB_URL)
    import asyncio

    # alembic env.py calls asyncio.run(); run it outside the running loop
    await asyncio.to_thread(_alembic_upgrade, TEST_DB_URL)
    yield
    from app.core.db import dispose_engine

    await dispose_engine()
