"""Experiment metrics: per-user values computed in the source and returned as aggregates (n, sum, sumsq)
per variant and segment, so user identifiers never leave the warehouse.

Each template produces neutral (postgres) SQL that the query service transpiles to the source dialect. Inputs:
the assignments table (experiment_key, user_id, variant, assigned_at, platform, country, source) and the marts
of the domain pack (mart_retention, payments). Maturity is relative to the freshest data, not the wall clock,
so a lagging warehouse never yields half-observed users.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.core.errors import ValidationFailed


@dataclass(frozen=True)
class ExpMetric:
    key: str
    name: str
    type: str  # binary | continuous
    days: int  # observation window after assignment (cohort maturity)
    semantic_keys: tuple[str, ...]  # semantic metrics this template corresponds to ("Create A/B" from a metric card)
    description: str
    unit: str = ""


TEMPLATES: dict[str, ExpMetric] = {
    m.key: m
    for m in (
        ExpMetric(
            "retention_d1",
            "Retention D1",
            "binary",
            1,
            ("retention_d1",),
            "Игрок активен на 1-й день после назначения",
            "%",
        ),
        ExpMetric(
            "retention_d7",
            "Retention D7",
            "binary",
            7,
            ("retention_d7", "retention_curve"),
            "Игрок активен на 7-й день",
            "%",
        ),
        ExpMetric(
            "conversion_d7",
            "Конверсия в платёж D7",
            "binary",
            7,
            ("payer_conversion", "payers"),
            "Хотя бы одна покупка за 7 дней",
            "%",
        ),
        ExpMetric(
            "arpu_d7",
            "ARPU D7 (покупки)",
            "continuous",
            7,
            ("arpu", "arppu", "iap_revenue", "revenue", "avg_check", "arpdau"),
            "Выручка от покупок на пользователя за 7 дней (нули включены)",
            "$",
        ),
        ExpMetric(
            "active_days_d7",
            "Активные дни D7",
            "continuous",
            7,
            ("sessions_per_user", "dau"),
            "Число дней с активностью за первые 7 дней",
        ),
    )
}

SEGMENTS = ("platform", "country", "source")
DATA_END = "(SELECT MAX(activity_date) FROM mart_retention)"


def get_template(metric_key: str) -> ExpMetric:
    m = TEMPLATES.get(metric_key)
    if m is None:
        raise ValidationFailed(f"Неизвестная метрика эксперимента: {metric_key}", details={"allowed": list(TEMPLATES)})
    return m


def template_for_semantic(semantic_key: str) -> ExpMetric | None:
    return next((m for m in TEMPLATES.values() if semantic_key in m.semantic_keys), None)


def _esc(v: str) -> str:
    return v.replace("'", "''")


def experiment_cohort(experiment_key: str, assignments_table: str, days: int) -> str:
    return (
        f"SELECT user_id, variant, assigned_at, platform, country, source FROM {assignments_table} "
        f"WHERE experiment_key = '{_esc(experiment_key)}' "
        f"AND CAST(assigned_at AS DATE) <= {DATA_END} - INTERVAL '{days} day'"
    )


def baseline_cohort(days: int, window_days: int = 28) -> str:
    """Recent matured installs as a stand-in population for planning (no experiment yet)."""
    return (
        f"SELECT user_id, 'A' AS variant, CAST(install_date AS TIMESTAMP) AS assigned_at, platform, country, source "
        f"FROM mart_retention WHERE day_n = 0 "
        f"AND install_date <= {DATA_END} - INTERVAL '{days} day' "
        f"AND install_date > {DATA_END} - INTERVAL '{days + window_days} day'"
    )


def _user_values(m: ExpMetric, cohort: str, segment: str | None) -> str:
    if segment is not None and segment not in SEGMENTS:
        raise ValidationFailed(f"Неизвестный сегмент: {segment}", details={"allowed": list(SEGMENTS)})
    seg = f"a.{segment}" if segment else "'all'"
    window = f"CAST(a.assigned_at AS DATE) + INTERVAL '{m.days} day'"
    if m.key.startswith("retention_d"):
        join = f"LEFT JOIN mart_retention r ON r.user_id = a.user_id AND r.day_n = {m.days}"
        value = "MAX(CASE WHEN r.user_id IS NULL THEN 0 ELSE 1 END)"
    elif m.key == "conversion_d7":
        join = f"LEFT JOIN payments p ON p.user_id = a.user_id AND p.event_date < {window}"
        value = "MAX(CASE WHEN p.user_id IS NULL THEN 0 ELSE 1 END)"
    elif m.key == "arpu_d7":
        join = f"LEFT JOIN payments p ON p.user_id = a.user_id AND p.event_date < {window}"
        value = "COALESCE(SUM(p.revenue_usd), 0)"
    else:  # active_days_d7
        join = f"LEFT JOIN mart_retention r ON r.user_id = a.user_id AND r.day_n < {m.days}"
        value = "COUNT(DISTINCT r.day_n)"
    return (
        f"SELECT a.user_id, a.variant, {seg} AS segment, {value} AS v FROM ({cohort}) a {join} "
        f"GROUP BY a.user_id, a.variant, {seg}"
    )


def aggregate_sql(metric_key: str, experiment_key: str, assignments_table: str, segment: str | None = None) -> str:
    m = get_template(metric_key)
    users = _user_values(m, experiment_cohort(experiment_key, assignments_table, m.days), segment)
    return f"SELECT u.variant, u.segment, COUNT(*) AS n, SUM(u.v) AS s, SUM(u.v * u.v) AS ss FROM ({users}) u GROUP BY 1, 2"


def values_sql(metric_key: str, experiment_key: str, assignments_table: str) -> str:
    """Per-user values WITHOUT identifiers (for the bootstrap of heavy-tailed metrics)."""
    m = get_template(metric_key)
    users = _user_values(m, experiment_cohort(experiment_key, assignments_table, m.days), None)
    return f"SELECT u.variant, u.v FROM ({users}) u"


def baseline_sql(metric_key: str, window_days: int = 28) -> str:
    m = get_template(metric_key)
    users = _user_values(m, baseline_cohort(m.days, window_days), None)
    return f"SELECT COUNT(*) AS n, SUM(u.v) AS s, SUM(u.v * u.v) AS ss FROM ({users}) u"


def assignment_counts_sql(experiment_key: str, assignments_table: str) -> str:
    """All assigned users per variant (immature included) — the input of the SRM check and progress."""
    return (
        f"SELECT variant, COUNT(DISTINCT user_id) AS n, MIN(assigned_at) AS first_at, MAX(assigned_at) AS last_at "
        f"FROM {assignments_table} WHERE experiment_key = '{_esc(experiment_key)}' GROUP BY 1"
    )
