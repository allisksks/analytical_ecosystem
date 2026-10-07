"""Connectors against real databases (TZ: integration tests on a real DBMS in Docker).

Ports follow deploy/docker-compose.dev.yml / CI services; tests are skipped when a server is unreachable.
"""

from __future__ import annotations

import asyncio
import os
import socket
from pathlib import Path

import pytest

from app.modules.connectors.base import ConnectorError, QueryTimeout
from app.modules.connectors.plugins.clickhouse import ClickHouseConnector
from app.modules.connectors.plugins.mysql import MySQLConnector
from app.modules.connectors.plugins.postgres import PostgresConnector

pytestmark = pytest.mark.integration


def _up(port: int) -> bool:
    with socket.socket() as s:
        s.settimeout(0.5)
        return s.connect_ex(("localhost", port)) == 0


CH_PORT = int(os.environ.get("TEST_CLICKHOUSE_PORT", "18123"))
MY_PORT = int(os.environ.get("TEST_MYSQL_PORT", "13306"))
PG_PORT = int(os.environ.get("TEST_PG_PORT", "55432"))


@pytest.mark.skipif(not _up(PG_PORT), reason="postgres not running")
async def test_postgres_catalog_limit_timeout() -> None:
    c = PostgresConnector(
        {
            "host": "localhost",
            "port": PG_PORT,
            "database": "postgres",
            "user": "postgres",
            "sslmode": "disable",
            "schemas": "pg_catalog",
        },
        {"password": "pg"},
    )
    try:
        assert (await c.test()).ok
        res = await c.execute("SELECT generate_series(1, 100) AS n", None, 10, 5, "q1")
        assert res.row_count == 10
        assert res.truncated
        assert [col.name for col in res.columns] == ["n"]
        with pytest.raises(QueryTimeout):
            await c.execute("SELECT pg_sleep(3)", None, 10, 1, "q2")
        catalog = await c.list_catalog()
        assert any(t.name == "pg_class" for t in catalog)
    finally:
        await c.close()


@pytest.mark.skipif(not _up(MY_PORT), reason="mysql not running")
async def test_mysql_catalog_and_read_only() -> None:
    c = MySQLConnector(
        {"host": "127.0.0.1", "port": MY_PORT, "database": "demo", "user": "root"}, {"password": "platform"}
    )
    try:
        assert (await c.test()).ok, (await c.test()).message
        pool = await c._get_pool()
        async with pool.acquire() as conn, conn.cursor() as cur:
            await cur.execute(
                "CREATE TABLE IF NOT EXISTS payments (id INT PRIMARY KEY, user_id VARCHAR(20), amount DOUBLE) COMMENT 'Платежи'"
            )
            await cur.execute("REPLACE INTO payments VALUES (1,'u1',9.99),(2,'u2',4.99),(3,'u1',1.5)")
        catalog = await c.list_catalog()
        t = next(t for t in catalog if t.name == "payments")
        assert [col.name for col in t.columns] == ["id", "user_id", "amount"]
        assert t.comment == "Платежи"
        res = await c.execute(
            "SELECT user_id, SUM(amount) AS s FROM payments GROUP BY user_id ORDER BY user_id", None, 1, 5, "m1"
        )
        assert res.rows == [["u1", 11.49]]
        assert res.truncated
        with pytest.raises(Exception, match=r"(?i)read.only"):
            await c.execute("DELETE FROM payments", None, 1, 5, "m2")
    finally:
        await c.close()


@pytest.mark.skipif(not _up(CH_PORT), reason="clickhouse not running")
async def test_clickhouse_with_demo_data(demo_dir: Path) -> None:
    from scripts.load_demo_clickhouse import load

    counts = load(f"http://platform:platform@localhost:{CH_PORT}", demo_dir, "demo_test")
    assert counts["events"] > 0
    c = ClickHouseConnector(
        {"host": "localhost", "port": CH_PORT, "database": "demo_test", "user": "platform"}, {"password": "platform"}
    )
    try:
        assert (await c.test()).ok
        catalog = {t.name: t for t in await c.list_catalog()}
        assert catalog["events"].row_count == counts["events"]
        res = await c.execute(
            "SELECT app_id, count() AS n FROM users GROUP BY app_id ORDER BY app_id", None, 100, 10, "c1"
        )
        assert [r[0] for r in res.rows] == ["bloom_merge", "drift_kings", "iron_shells"]
        with pytest.raises(ConnectorError, match=r"(?i)readonly"):
            await c.execute("INSERT INTO users (app_id) VALUES ('x')", None, 1, 5, "c2")
        with pytest.raises(QueryTimeout):
            await c.execute("SELECT count() FROM numbers(100000000000)", None, 1, 1, "c3")
        # cancellation by query id
        task = asyncio.create_task(c.execute("SELECT count() FROM numbers(100000000000)", None, 1, 60, "c4"))
        await asyncio.sleep(1)
        await c.cancel("c4")
        with pytest.raises(ConnectorError):
            await asyncio.wait_for(task, 10)
    finally:
        await c.close()
