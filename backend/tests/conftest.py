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
os.environ.setdefault("COOKIE_SECURE", "false")

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


# ----------------------------------------------------------------------------- app & data fixtures
from collections.abc import Callable  # noqa: E402
from datetime import timedelta  # noqa: E402
from typing import Any  # noqa: E402

from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy import text  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: E402


@pytest.fixture
async def db() -> AsyncIterator[AsyncSession]:
    from app.core.db import Base, get_sessionmaker
    from app.models import load_all_models

    load_all_models()
    async with get_sessionmaker()() as session:
        yield session
        await session.rollback()
        tables = ", ".join(f'"{t.name}"' for t in Base.metadata.sorted_tables)
        await session.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))
        await session.commit()


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    from app.main import create_app

    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test/api/v1") as c:
        yield c


class World:
    """A small organisation: 2 projects and users for several roles."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.users: dict[str, Any] = {}
        self.projects: dict[str, Any] = {}

    async def setup(self) -> World:
        from app.modules.iam.models import Project
        from app.modules.iam.service import create_organization, grant

        self.org = await create_organization(self.db, "Test Org", "test-org")
        from app.modules.iam.service import ensure_builtin_roles

        self.roles = await ensure_builtin_roles(self.db, self.org.id)
        for key in ("alpha", "beta"):
            p = Project(org_id=self.org.id, key=key, name=key.title(), data_scope={"app_id": [key]})
            self.db.add(p)
            self.projects[key] = p
        await self.db.flush()
        await self.add_user("admin", "admin", None)
        await self.add_user("analyst", "analyst", ["alpha"])
        await self.add_user("marketing", "marketing", ["beta"])
        await self.add_user("ceo", "executive", None)
        await self.db.commit()
        _ = grant
        return self

    async def add_user(self, name: str, role: str, projects: list[str] | None, password: str = "Passw0rd-123"):  # type: ignore[no-untyped-def]
        from app.modules.iam.service import create_user, grant

        user = await create_user(self.db, self.org.id, f"{name}@test.io", name.title(), password)
        if projects is None:
            await grant(self.db, user, self.roles[role], None)
        else:
            for p in projects:
                await grant(self.db, user, self.roles[role], self.projects[p])
        self.users[name] = user
        return user

    def headers(self, name: str) -> dict[str, str]:
        from app.modules.iam.security import issue_token

        user = self.users[name]
        token = issue_token("access", user.id, timedelta(minutes=5), org=str(user.org_id))
        return {"Authorization": f"Bearer {token}"}


@pytest.fixture
async def world(db: AsyncSession) -> World:
    return await World(db).setup()


@pytest.fixture
def as_user(world: World) -> Callable[[str], dict[str, str]]:
    return world.headers


@pytest.fixture(scope="session")
def demo_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Small deterministic copy of the demo dataset shared by data tests."""
    from datetime import date

    from scripts.generate_demo_data import generate

    out = tmp_path_factory.mktemp("demo")
    generate(out, scale=0.03, days=60, end=date(2026, 5, 31), seed=11)
    return out


@pytest.fixture
async def demo_source(world: World, demo_dir: Path) -> Any:
    """Demo files source available to every project, catalog loaded; projects scoped to two games."""
    from app.modules.connectors.models import DataSource
    from app.modules.connectors.service import refresh_catalog

    world.projects["alpha"].data_scope = {"app_id": ["iron_shells"]}
    world.projects["beta"].data_scope = {"app_id": ["drift_kings"]}
    source = DataSource(org_id=world.org.id, name="demo", type="files", config={"path": str(demo_dir)}, row_limit=1000)
    world.db.add(source)
    await world.db.flush()
    await refresh_catalog(world.db, source)
    await world.db.commit()
    return source
