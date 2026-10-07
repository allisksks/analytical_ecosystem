from __future__ import annotations

from collections import Counter

import pytest
import sqlglot

from app.core.errors import ValidationFailed
from app.modules.experiments import metrics, splitter


def test_assignment_is_deterministic_and_follows_weights() -> None:
    variants = [("A", 0.5), ("B", 0.3), ("C", 0.2)]
    first = [splitter.assign("exp", f"u{i}", variants) for i in range(20_000)]
    assert first == [splitter.assign("exp", f"u{i}", variants) for i in range(20_000)]
    shares = {k: n / len(first) for k, n in Counter(first).items()}
    assert shares["A"] == pytest.approx(0.5, abs=0.015)
    assert shares["B"] == pytest.approx(0.3, abs=0.015)
    assert shares["C"] == pytest.approx(0.2, abs=0.015)
    # another experiment reshuffles users independently
    other = [splitter.assign("exp2", f"u{i}", variants) for i in range(20_000)]
    assert sum(a == b for a, b in zip(first, other, strict=True)) / len(first) < 0.45


def test_traffic_share_does_not_reshuffle_variants() -> None:
    variants = [("A", 1.0), ("B", 1.0)]
    half = {u: splitter.assign("exp", u, variants, traffic_share=0.5) for u in (f"u{i}" for i in range(10_000))}
    full = {u: splitter.assign("exp", u, variants, traffic_share=1.0) for u in half}
    inside = [u for u, v in half.items() if v is not None]
    assert len(inside) / len(half) == pytest.approx(0.5, abs=0.02)
    assert all(full[u] == half[u] for u in inside)  # growing traffic keeps earlier users in their variant


@pytest.mark.parametrize("metric", sorted(metrics.TEMPLATES))
@pytest.mark.parametrize("dialect", ["duckdb", "postgres", "clickhouse", "mysql"])
def test_metric_sql_transpiles(metric: str, dialect: str) -> None:
    for sql in (
        metrics.aggregate_sql(metric, "it's", "ab_assignments", "platform"),
        metrics.values_sql(metric, "k", "ab_assignments"),
        metrics.baseline_sql(metric),
    ):
        assert sqlglot.transpile(sql, read="postgres", write=dialect)
    assert "'it''s'" in metrics.aggregate_sql(metric, "it's", "ab_assignments")


def test_unknown_metric_or_segment() -> None:
    with pytest.raises(ValidationFailed):
        metrics.aggregate_sql("nope", "k", "t")
    with pytest.raises(ValidationFailed):
        metrics.aggregate_sql("retention_d1", "k", "t", "user_id")
    assert metrics.template_for_semantic("payer_conversion").key == "conversion_d7"  # type: ignore[union-attr]
    assert metrics.template_for_semantic("unknown") is None
