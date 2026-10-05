from __future__ import annotations

from pathlib import Path

import pytest
import sqlglot

from app.modules.ai import exam, prompts


@pytest.fixture(scope="module")
def pairs() -> list[prompts.GoldenPair]:
    return prompts.load_golden()


def test_golden_set_size_and_dialects(pairs: list[prompts.GoldenPair]) -> None:
    assert 80 <= len(pairs) <= 100  # TZ: 80–100 pairs
    assert len({p.id for p in pairs}) == len(pairs)
    for p in pairs:
        for dialect in ("duckdb", "clickhouse", "postgres", "mysql"):
            assert sqlglot.transpile(p.sql, read="postgres", write=dialect), (p.id, dialect)


def test_every_reference_query_runs_on_demo_data(pairs: list[prompts.GoldenPair], demo_dir_full: Path) -> None:
    con = exam.connect(demo_dir_full)
    non_empty = 0
    for p in pairs:  # every reference query executes (tiny fixture data may have empty days)
        non_empty += bool(con.execute(sqlglot.transpile(p.sql, read="postgres", write="duckdb")[0]).fetchall())
    assert non_empty >= len(pairs) * 0.9


def test_same_result() -> None:
    assert exam.same_result([(1, 2.00001)], [(2.0, 1)], ordered=False)
    assert exam.same_result([("a", 1), ("b", 2)], [("b", 2), ("a", 1)], ordered=False)
    assert not exam.same_result([("a", 1), ("b", 2)], [("b", 2), ("a", 1)], ordered=True)
    assert exam.same_result([("ios", 10)], [("ios", "iOS label", 10)], ordered=False)  # extra column tolerated
    assert not exam.same_result([(1,)], [(1,), (2,)], ordered=False)


async def test_exam_scores_execution_accuracy(pairs: list[prompts.GoldenPair], demo_dir_full: Path) -> None:
    by_question = {p.question: p for p in pairs}
    sample = pairs[:20]

    async def generate(messages: list[dict[str, str]]) -> str:
        p = by_question[messages[-1]["content"]]
        # examples never contain the question itself (leave-one-out)
        assert all(m["content"] != p.question for m in messages[1:-1])
        if p.id in {s.id for s in sample[:5]}:
            return "```sql\nSELECT 42 AS wrong\n```"
        return f"```sql\n{sqlglot.transpile(p.sql, read='postgres', write='duckdb')[0]}\n```"

    report = await exam.run_exam(exam.connect(demo_dir_full), sample, generate, model="fake")
    assert (report.correct, report.total) == (15, 20)
    assert report.accuracy == 0.75 and report.passed
    assert "15/20" in report.markdown()


def test_example_selection_prefers_similar_questions(pairs: list[prompts.GoldenPair]) -> None:
    tables = {"events", "payments", "users", "mart_retention"}
    ex = prompts.select_examples("Какая выручка от покупок была позавчера?", pairs, tables, k=3)
    assert ex[0].id == "iap_revenue_yesterday"
    assert all(e.tables <= tables for e in ex)
    msgs = prompts.sql_messages("q", "clickhouse", [prompts.TableDoc("events", [("event_date", "Date", "")])], ex)
    assert len(msgs) == 2 + 2 * len(ex) and "clickhouse" in msgs[0]["content"]
    assert prompts.extract_sql("Вот:\n```sql\nSELECT 1;\n```\nпояснение") == ("SELECT 1", "Вот:\n\nпояснение")


def test_top_n_ties_are_tolerated() -> None:
    assert exam.same_result([("US", 5), ("DE", 3)], [("US", 5), ("FR", 3)], ordered=True, top=True)
    assert not exam.same_result([("US", 5), ("DE", 3)], [("US", 5), ("FR", 2)], ordered=True, top=True)
