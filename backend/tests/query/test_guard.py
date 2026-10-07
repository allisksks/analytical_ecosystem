from __future__ import annotations

import duckdb
import pytest

from app.modules.query.guard import GuardError, TableInfo, guard

EVENTS = TableInfo("main", "events", ("app_id", "user_id", "device_id", "event_name"), frozenset({"device_id"}))
USERS = TableInfo("main", "users", ("app_id", "user_id", "country"))
CATALOG = {"events": EVENTS, "users": USERS}


def resolve(schema: str, name: str) -> TableInfo | None:
    t = CATALOG.get(name.lower())
    return t if t and schema in ("", "main") else None


@pytest.mark.parametrize(
    "sql",
    [
        "DELETE FROM events",
        "DROP TABLE events",
        "INSERT INTO events SELECT * FROM events",
        "SELECT 1; SELECT 2",
        "SELECT * INTO copy FROM events",
        "SELECT * FROM read_csv('/etc/passwd')",
        "SELECT getenv('HOME')",
        "SELECT * FROM events FOR UPDATE",
        "SELECT * FROM information_schema.tables",
        "SELECT * FROM secret_table",
        "COPY events TO '/tmp/x.csv'",
        "SET threads = 1",
        "PRAGMA version",
        "",
    ],
)
def test_rejects_non_read_only_and_unknown(sql: str) -> None:
    with pytest.raises(GuardError):
        guard(sql, "duckdb", resolve)


@pytest.mark.parametrize(
    ("dialect", "sql"),
    [
        ("postgres", "SELECT pg_read_file('/etc/passwd')"),
        ("postgres", "SELECT query_to_xml('select * from users', true, true, '')"),
        ("postgres", "SELECT pg_sleep(100)"),
        ("mysql", "SELECT load_file('/etc/passwd')"),
        ("clickhouse", "SELECT * FROM url('http://evil', CSV, 'a String')"),
        ("clickhouse", "SELECT * FROM remote('other:9000', db.t)"),
        ("clickhouse", "SELECT dictGet('d', 'x', 1)"),
    ],
)
def test_rejects_dangerous_functions_per_dialect(dialect: str, sql: str) -> None:
    with pytest.raises(GuardError):
        guard(sql, dialect, resolve)


def _db() -> duckdb.DuckDBPyConnection:
    con = duckdb.connect()
    con.execute(
        "CREATE TABLE events AS SELECT * FROM (VALUES ('a','u1','d1','start'),('a','u2','d2','start'),"
        "('b','u3','d3','start')) t(app_id, user_id, device_id, event_name)"
    )
    con.execute(
        "CREATE TABLE users AS SELECT * FROM (VALUES ('a','u1','US'),('b','u3','DE')) t(app_id,user_id,country)"
    )
    return con


def test_row_filter_applies_to_every_reference_including_joins_and_ctes() -> None:
    sql = """
        WITH x AS (SELECT e.user_id FROM events AS e)
        SELECT count(*) FROM x JOIN users u ON u.user_id = x.user_id
    """
    res = guard(sql, "duckdb", resolve, row_filters={"app_id": ["a"]})
    assert set(res.filtered) == {"events.app_id", "users.app_id"}
    assert _db().execute(res.sql).fetchone() == (1,)


def test_empty_scope_returns_nothing() -> None:
    res = guard("SELECT count(*) FROM events", "duckdb", resolve, row_filters={"app_id": []})
    assert _db().execute(res.sql).fetchone() == (0,)


def test_pii_is_hashed_but_countable() -> None:
    res = guard("SELECT device_id, count(DISTINCT device_id) OVER () AS n FROM events", "duckdb", resolve)
    rows = _db().execute(res.sql).fetchall()
    assert all(len(r[0]) == 32 and r[0] != "d1" for r in rows)
    assert rows[0][1] == 3
    unmasked = guard("SELECT device_id FROM events", "duckdb", resolve, mask_pii=False)
    assert {r[0] for r in _db().execute(unmasked.sql).fetchall()} == {"d1", "d2", "d3"}


def test_values_are_escaped() -> None:
    res = guard("SELECT * FROM users", "duckdb", resolve, row_filters={"app_id": ["a' OR '1'='1"]})
    assert _db().execute(res.sql).fetchall() == []


def test_limit_is_enforced() -> None:
    assert "LIMIT 5" in guard("SELECT * FROM users", "duckdb", resolve, limit=5).sql
    assert "LIMIT 2" in guard("SELECT * FROM users LIMIT 2", "duckdb", resolve, limit=5).sql
    assert "LIMIT 5" in guard("SELECT * FROM users LIMIT 1000", "duckdb", resolve, limit=5).sql
    union = guard("SELECT user_id FROM users UNION ALL SELECT user_id FROM events", "duckdb", resolve, limit=3)
    assert len(_db().execute(union.sql).fetchall()) == 3


@pytest.mark.parametrize("dialect", ["postgres", "clickhouse", "mysql", "duckdb"])
def test_rewritten_sql_is_valid_in_each_dialect(dialect: str) -> None:
    res = guard(
        "SELECT e.device_id FROM events e WHERE e.event_name = 'x'",
        dialect,
        resolve,
        row_filters={"app_id": ["a"]},
        limit=10,
    )
    assert "WHERE" in res.sql
    assert "MD5" in res.sql.upper()
