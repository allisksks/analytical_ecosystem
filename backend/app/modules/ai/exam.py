"""Golden-set exam of the SQL assistant (TZ: ≥70% of questions answered correctly).

Execution accuracy: the generated SQL and the reference SQL run on the same data; the answer is correct when the
result sets match (order-insensitive unless the question asks for a top/order, floats rounded, column names
ignored). Few-shot examples are chosen leave-one-out, so a question never sees its own reference.
"""

from __future__ import annotations

import math
import time
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import duckdb
import sqlglot

from app.modules.ai import prompts

TABLES = (
    "users",
    "events",
    "payments",
    "ad_revenue",
    "ab_assignments",
    "mart_retention",
    "mart_monetisation",
    "mart_portfolio",
    "mart_ua",
)
Generate = Callable[[list[dict[str, str]]], Awaitable[str]]


@dataclass
class ExamItem:
    id: str
    question: str
    correct: bool
    generated_sql: str
    error: str = ""
    latency_ms: float = 0


@dataclass
class ExamReport:
    total: int
    correct: int
    accuracy: float
    threshold: float
    passed: bool
    model: str
    items: list[ExamItem] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

    def markdown(self) -> str:
        lines = [
            f"# Экзамен SQL-ассистента: {self.correct}/{self.total} = {self.accuracy:.1%} "
            f"({'сдан' if self.passed else 'не сдан'}, порог {self.threshold:.0%})",
            f"Модель: `{self.model}`",
            "",
            "| # | Вопрос | Итог | Ошибка |",
            "|---|---|---|---|",
        ]
        for i, it in enumerate(self.items, 1):
            lines.append(f"| {i} | {it.question} | {'✅' if it.correct else '❌'} | {it.error[:120]} |")
        return "\n".join(lines)


def connect(data_dir: Path, app_id: str = "iron_shells") -> duckdb.DuckDBPyConnection:
    con = duckdb.connect()
    for t in TABLES:
        path = data_dir / f"{t}.parquet"
        if path.exists():
            con.execute(f"CREATE VIEW {t} AS SELECT * FROM read_parquet('{path}') WHERE app_id = '{app_id}'")
    return con


def table_docs(con: duckdb.DuckDBPyConnection) -> list[prompts.TableDoc]:
    docs = []
    for (name,) in con.execute("SELECT view_name FROM duckdb_views() WHERE NOT internal ORDER BY 1").fetchall():
        cols = con.execute(f"DESCRIBE {name}").fetchall()
        docs.append(prompts.TableDoc(name, [(c[0], c[1], "") for c in cols if c[0] != "app_id"]))
    return docs


def _norm(v: Any) -> Any:
    if isinstance(v, Decimal):
        v = float(v)
    if isinstance(v, bool):
        return int(v)
    if isinstance(v, int | float):
        f = float(v)
        if math.isnan(f):
            return None
        return round(f, 3) if abs(f) < 1e6 else round(f)
    if isinstance(v, datetime):
        return v.date().isoformat() if v.time() == datetime.min.time() else v.isoformat()
    if isinstance(v, date):
        return v.isoformat()
    return v


def _row_key(row: tuple[Any, ...]) -> tuple[str, ...]:
    return tuple(sorted(repr(_norm(v)) for v in row))


def _numbers(row: tuple[Any, ...]) -> tuple[Any, ...]:
    return tuple(sorted(_norm(v) for v in row if isinstance(_norm(v), int | float)))


def same_result(expected: list[tuple[Any, ...]], got: list[tuple[Any, ...]], ordered: bool, top: bool = False) -> bool:
    """Column order/names do not matter; extra columns in the answer are tolerated if all expected ones match.
    For top-N questions rows tied on the ranking value may legitimately differ: then the values are compared."""
    if len(expected) != len(got):
        return False
    if top and not _same(expected, got, ordered):
        return [_numbers(r) for r in expected] == [_numbers(r) for r in got] and any(_numbers(r) for r in expected)
    return _same(expected, got, ordered)


def _same(expected: list[tuple[Any, ...]], got: list[tuple[Any, ...]], ordered: bool) -> bool:
    exp_rows = [_row_key(r) for r in expected]
    got_rows = [_row_key(r) for r in got]
    if all(len(r) == len(e) for r, e in zip(got_rows, exp_rows, strict=True)):
        return exp_rows == got_rows if ordered else sorted(exp_rows) == sorted(got_rows)
    # the model added columns (e.g. a label): every expected value must be present in the matching row
    pairs = zip(exp_rows, got_rows, strict=True) if ordered else zip(sorted(exp_rows), sorted(got_rows), strict=True)
    return all(set(e) <= set(g) for e, g in pairs)


def _run(con: duckdb.DuckDBPyConnection, sql: str) -> list[tuple[Any, ...]]:
    duck = sqlglot.transpile(sql, read="duckdb", write="duckdb")[0]
    return con.execute(duck).fetchall()


async def run_exam(
    con: duckdb.DuckDBPyConnection,
    pairs: list[prompts.GoldenPair],
    generate: Generate,
    *,
    model: str = "",
    threshold: float = 0.7,
    on_item: Callable[[ExamItem], None] | None = None,
) -> ExamReport:
    tables = table_docs(con)
    names = {t.name for t in tables}
    items: list[ExamItem] = []
    for pair in pairs:
        expected = _run(con, sqlglot.transpile(pair.sql, read="postgres", write="duckdb")[0])
        examples = prompts.select_examples(pair.question, pairs, names, exclude=pair.id)
        messages = prompts.sql_messages(pair.question, "duckdb", tables, examples)
        started = time.perf_counter()
        sql, error, ok = "", "", False
        try:
            sql, _ = prompts.extract_sql(await generate(messages))
            low = pair.sql.lower()
            top = "order by" in low and "limit" in low
            ok = same_result(expected, _run(con, sql), ordered=top, top=top)
            if not ok:
                error = "результат не совпал с эталоном"
        except Exception as exc:
            error = str(exc).splitlines()[0][:300]
        item = ExamItem(pair.id, pair.question, ok, sql, error, (time.perf_counter() - started) * 1000)
        items.append(item)
        if on_item:
            on_item(item)
    correct = sum(i.correct for i in items)
    accuracy = correct / len(items) if items else 0.0
    return ExamReport(len(items), correct, accuracy, threshold, accuracy >= threshold, model, items)
