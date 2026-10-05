from __future__ import annotations

from datetime import date
from pathlib import Path

import duckdb

from scripts.generate_demo_data import generate


def test_generator_produces_all_tables_and_stories(tmp_path: Path) -> None:
    counts = generate(tmp_path, scale=0.05, days=91, end=date(2026, 5, 31), seed=7)
    expected = {"users", "events", "payments", "ad_revenue", "ab_assignments", "mart_retention",
                "mart_monetisation", "mart_portfolio", "mart_ua"}  # fmt: skip
    assert expected <= set(counts)
    assert all(counts[t] > 0 for t in expected)
    con = duckdb.connect()
    # install day is always day_n = 0 and every user has it
    users, d0 = con.execute(
        f"SELECT (SELECT count(*) FROM '{tmp_path}/users.parquet'),"
        f" (SELECT count(*) FROM '{tmp_path}/mart_retention.parquet' WHERE day_n = 0)"
    ).fetchone()  # type: ignore[misc]
    assert users == d0
    # deterministic for a given seed
    counts2 = generate(tmp_path / "again", scale=0.05, days=91, end=date(2026, 5, 31), seed=7)
    assert counts == counts2
