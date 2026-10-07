"""A/B experiments: design checks, lifecycle with approval, recalculation from the warehouse, knowledge export."""

from __future__ import annotations

import math
import uuid
from collections import defaultdict
from datetime import UTC, datetime
from typing import Any

import numpy as np
import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError, NotFoundError, PermissionDenied, ValidationFailed
from app.modules.audit.service import record
from app.modules.connectors.models import DataSource
from app.modules.connectors.service import source_allowed_in
from app.modules.experiments import metrics, splitter, stats
from app.modules.experiments.models import Experiment, ExperimentSnapshot
from app.modules.experiments.schemas import (
    Comparison,
    ExperimentResult,
    FrequentistOut,
    MetricResult,
    SegmentResult,
    SrmOut,
    VariantStat,
)
from app.modules.iam.models import Project
from app.modules.iam.permissions import P
from app.modules.iam.policy import Principal
from app.modules.iam.service import system_principal
from app.modules.kb import service as kb_service
from app.modules.query import service as query_service

log = structlog.get_logger("experiments")

DESIGN_FIELDS = (
    "metric_key",
    "secondary_metrics",
    "variants",
    "traffic_share",
    "segments",
    "mde",
    "alpha",
    "power",
    "splitter",
    "source_id",
    "assignments_table",
)
# (from, to) -> permission
TRANSITIONS: dict[tuple[str, str], str] = {
    ("draft", "review"): P.EXPERIMENTS_PROPOSE,
    ("review", "draft"): P.EXPERIMENTS_PROPOSE,  # withdraw or send back for changes
    ("review", "running"): P.EXPERIMENTS_APPROVE,
    ("running", "completed"): P.EXPERIMENTS_EDIT,
    ("completed", "archived"): P.EXPERIMENTS_EDIT,
    ("draft", "archived"): P.EXPERIMENTS_EDIT,
}
VALUES_LIMIT = 100_000  # bootstrap input cap (per-user values, no identifiers)
KB_DECISION = {"ship": "accepted", "keep_control": "rejected", "inconclusive": "inconclusive"}


# ---------------------------------------------------------------- access
def can_view_all(principal: Principal, project_id: uuid.UUID) -> bool:
    return principal.can(P.EXPERIMENTS_VIEW, project_id)


def require_view(principal: Principal, project_id: uuid.UUID) -> None:
    if not (principal.can(P.EXPERIMENTS_VIEW, project_id) or principal.can(P.EXPERIMENTS_RESULTS, project_id)):
        raise PermissionDenied("Недостаточно прав", details={"permission": P.EXPERIMENTS_VIEW})


def visible(principal: Principal, exp: Experiment) -> bool:
    """Roles with ``experiments:results`` only (executives, marketing) see finished experiments."""
    if can_view_all(principal, exp.project_id):
        return True
    return principal.can(P.EXPERIMENTS_RESULTS, exp.project_id) and exp.status in ("completed", "archived")


async def get_experiment(db: AsyncSession, principal: Principal, experiment_id: uuid.UUID) -> Experiment:
    exp = await db.get(Experiment, experiment_id)
    if exp is None or exp.org_id != principal.org_id:
        raise NotFoundError("Эксперимент не найден")
    projects = principal.visible_project_ids()
    if (projects is not None and exp.project_id not in projects) or not visible(principal, exp):
        raise NotFoundError("Эксперимент не найден")
    return exp


async def _source(db: AsyncSession, exp: Experiment) -> DataSource:
    if exp.source_id is None:
        raise ValidationFailed("Не выбран источник данных с назначениями пользователей")
    source = await db.get(DataSource, exp.source_id)
    if source is None or source.org_id != exp.org_id:
        raise ValidationFailed("Источник данных эксперимента не найден")
    if not source_allowed_in(source, exp.project_id):
        raise ValidationFailed("Источник не подключён к проекту эксперимента")
    return source


# ---------------------------------------------------------------- design
def _check_design(data: dict[str, Any]) -> None:
    metrics.get_template(data["metric_key"])
    for m in data.get("secondary_metrics") or []:
        metrics.get_template(m)
    bad = sorted(set(data.get("segments") or []) - set(metrics.SEGMENTS))
    if bad:
        raise ValidationFailed(f"Неизвестные сегменты: {', '.join(bad)}", details={"allowed": list(metrics.SEGMENTS)})


def _normalise_variants(variants: list[dict[str, Any]]) -> list[dict[str, Any]]:
    total = sum(float(v["weight"]) for v in variants)
    return [{**v, "weight": round(float(v["weight"]) / total, 6), "name": v.get("name") or v["key"]} for v in variants]


async def _check_source(db: AsyncSession, principal: Principal, project: Project, source_id: uuid.UUID | None) -> None:
    if source_id is None:
        return
    source = await db.get(DataSource, source_id)
    if source is None or source.org_id != principal.org_id or not source_allowed_in(source, project.id):
        raise ValidationFailed("Источник не найден или не подключён к проекту")


async def create(db: AsyncSession, principal: Principal, project: Project, data: dict[str, Any]) -> Experiment:
    if not (principal.can(P.EXPERIMENTS_PROPOSE, project.id) or principal.can(P.EXPERIMENTS_EDIT, project.id)):
        raise PermissionDenied("Недостаточно прав", details={"permission": P.EXPERIMENTS_PROPOSE})
    _check_design(data)
    await _check_source(db, principal, project, data.get("source_id"))
    if await db.scalar(select(Experiment.id).where(Experiment.project_id == project.id, Experiment.key == data["key"])):
        raise ConflictError(f"Эксперимент с ключом {data['key']} уже есть в проекте")
    variants = data.get("variants") or [
        {"key": "A", "name": "Контроль", "weight": 0.5},
        {"key": "B", "name": "Тест", "weight": 0.5},
    ]
    data = {**data, "variants": _normalise_variants(variants)}
    data.pop("project_id", None)
    exp = Experiment(
        org_id=principal.org_id,
        project_id=project.id,
        status="draft",
        created_by=principal.label,
        **{**data, "owner": data.get("owner") or principal.label},
    )
    db.add(exp)
    await db.flush()
    await record(
        db,
        "experiment.create",
        principal=principal,
        resource_type="experiment",
        resource_id=exp.id,
        project_id=project.id,
        details={"key": exp.key},
    )
    return exp


async def update(db: AsyncSession, principal: Principal, exp: Experiment, changes: dict[str, Any]) -> Experiment:
    if not (
        principal.can(P.EXPERIMENTS_EDIT, exp.project_id)
        or (
            principal.can(P.EXPERIMENTS_PROPOSE, exp.project_id)
            and exp.created_by == principal.label
            and exp.status == "draft"
        )
    ):
        raise PermissionDenied("Недостаточно прав", details={"permission": P.EXPERIMENTS_EDIT})
    design = set(changes) & set(DESIGN_FIELDS)
    if design and exp.status not in ("draft", "review"):
        raise ConflictError("Дизайн запущенного эксперимента менять нельзя — создайте новый эксперимент")
    merged = {f: getattr(exp, f) for f in DESIGN_FIELDS} | changes
    _check_design(merged)
    if "source_id" in changes:
        project = await db.get(Project, exp.project_id)
        assert project is not None
        await _check_source(db, principal, project, changes["source_id"])
    if "variants" in changes:
        changes["variants"] = _normalise_variants(changes["variants"])
    for k, v in changes.items():
        setattr(exp, k, v)
    await record(
        db,
        "experiment.update",
        principal=principal,
        resource_type="experiment",
        resource_id=exp.id,
        project_id=exp.project_id,
        details={"fields": sorted(changes)},
    )
    return exp


async def transition(db: AsyncSession, principal: Principal, exp: Experiment, to: str, comment: str = "") -> Experiment:
    permission = TRANSITIONS.get((exp.status, to))
    if permission is None:
        raise ConflictError(f"Переход {exp.status} → {to} недопустим")
    principal.require(permission, exp.project_id)
    if to == "running":
        await _source(db, exp)
        exp.started_at = exp.started_at or datetime.now(UTC)
        exp.approved_by = principal.label
    if to == "completed":
        exp.ended_at = datetime.now(UTC)
    previous, exp.status = exp.status, to
    await record(
        db,
        f"experiment.{to}",
        principal=principal,
        resource_type="experiment",
        resource_id=exp.id,
        project_id=exp.project_id,
        details={"from": previous, "comment": comment},
    )
    return exp


async def decide(db: AsyncSession, principal: Principal, exp: Experiment, decision: str, conclusion: str) -> Experiment:
    principal.require(P.EXPERIMENTS_APPROVE, exp.project_id)
    if exp.status != "completed":
        raise ConflictError("Решение фиксируется после остановки эксперимента")
    exp.decision, exp.conclusion, exp.decided_by = decision, conclusion, principal.label
    await record(
        db,
        "experiment.decide",
        principal=principal,
        resource_type="experiment",
        resource_id=exp.id,
        project_id=exp.project_id,
        details={"decision": decision},
    )
    return exp


# ---------------------------------------------------------------- calculation
def _f(v: Any) -> float:
    return float(v) if v is not None else 0.0


def _group(row: dict[str, Any]) -> stats.GroupStats:
    return stats.GroupStats(int(row["n"]), _f(row["s"]), _f(row["ss"]))


def _variant_stat(key: str, g: stats.GroupStats) -> VariantStat:
    return VariantStat(key=key, n=g.n, mean=g.mean, sd=math.sqrt(g.var))


def _compare(
    metric_type: str,
    control: stats.GroupStats,
    treatment: stats.GroupStats,
    alpha: float,
    values: tuple[np.ndarray, np.ndarray] | None = None,
) -> Comparison | None:
    if control.n < 2 or treatment.n < 2:
        return None
    if metric_type == "binary":
        bayes = stats.bayes_binary(control, treatment)
        freq = stats.z_test_proportions(control, treatment, alpha)
    else:
        if values is not None and len(values[0]) >= 2 and len(values[1]) >= 2:
            bayes = stats.bayes_bootstrap(values[0], values[1])
        else:
            bayes = stats.bayes_continuous(control, treatment)
        freq = stats.welch_t_test(control, treatment, alpha)
    return Comparison(
        variant="",
        prob_better=bayes.prob_b_better,
        lift=bayes.lift_mean,
        lift_ci=bayes.lift_ci,
        expected_loss=bayes.expected_loss_b,
        posterior_control=bayes.posterior_a,
        posterior_variant=bayes.posterior_b,
        method=bayes.method,
        frequentist=FrequentistOut(
            method=freq.method, p_value=freq.p_value, diff=freq.diff, ci=freq.ci, significant=freq.significant
        ),
    )


async def _rows(
    db: AsyncSession, principal: Principal, source: DataSource, project: Project, sql: str, limit: int = 10_000
) -> list[dict[str, Any]] | None:
    """Rows as dicts; ``None`` when the result did not fit into ``limit`` (callers decide whether that is fatal)."""
    out = await query_service.execute(db, principal, source, project, sql, origin="experiments", limit=limit)
    if out.truncated:
        return None
    names = [c["name"] for c in out.columns]
    return [dict(zip(names, r, strict=True)) for r in out.rows]


async def _agg(
    db: AsyncSession, principal: Principal, source: DataSource, project: Project, sql: str
) -> list[dict[str, Any]]:
    rows = await _rows(db, principal, source, project, sql)
    if rows is None:
        raise ValidationFailed("Слишком много групп или сегментов в результате агрегации")
    return rows


async def _metric_result(
    db: AsyncSession,
    principal: Principal,
    source: DataSource,
    project: Project,
    exp: Experiment,
    metric_key: str,
    with_segments: bool,
) -> tuple[MetricResult, list[SegmentResult]]:
    tpl = metrics.get_template(metric_key)
    keys = [v["key"] for v in exp.variants]
    control_key = keys[0]
    rows = await _agg(db, principal, source, project, metrics.aggregate_sql(metric_key, exp.key, exp.assignments_table))
    groups = {str(r["variant"]): _group(r) for r in rows}
    empty = stats.GroupStats(0, 0.0, 0.0)
    values: dict[str, np.ndarray] = {}
    if tpl.type == "continuous":
        vrows = await _rows(
            db, principal, source, project, metrics.values_sql(metric_key, exp.key, exp.assignments_table), VALUES_LIMIT
        )
        if vrows is not None:  # too many users: the normal approximation is accurate enough then
            buckets: dict[str, list[float]] = defaultdict(list)
            for r in vrows:
                buckets[str(r["variant"])].append(_f(r["v"]))
            values = {k: np.asarray(v, dtype=float) for k, v in buckets.items()}

    def comparisons(gs: dict[str, stats.GroupStats], vals: dict[str, np.ndarray]) -> list[Comparison]:
        out = []
        for k in keys[1:]:
            pair = (vals[control_key], vals[k]) if control_key in vals and k in vals else None
            c = _compare(tpl.type, gs.get(control_key, empty), gs.get(k, empty), exp.alpha, pair)
            if c is not None:
                c.variant = k
                out.append(c)
        return out

    result = MetricResult(
        metric=tpl.key,
        name=tpl.name,
        type=tpl.type,
        unit=tpl.unit,
        variants=[_variant_stat(k, groups.get(k, empty)) for k in keys],
        comparisons=comparisons(groups, values),
    )
    segments: list[SegmentResult] = []
    if with_segments:
        weights = [float(v["weight"]) for v in exp.variants]
        for seg in exp.segments:
            sql = metrics.aggregate_sql(metric_key, exp.key, exp.assignments_table, seg)
            by_value: dict[str, dict[str, stats.GroupStats]] = defaultdict(dict)
            for r in await _agg(db, principal, source, project, sql):
                by_value[str(r["segment"])][str(r["variant"])] = _group(r)
            for value, gs in sorted(by_value.items(), key=lambda kv: -sum(g.n for g in kv[1].values())):
                srm = stats.srm([gs.get(k, empty).n for k in keys], weights)
                segments.append(
                    SegmentResult(
                        segment=seg,
                        value=value,
                        variants=[_variant_stat(k, gs.get(k, empty)) for k in keys],
                        comparisons=comparisons(gs, {}),
                        srm_mismatch=srm.mismatch,
                    )
                )
    return result, segments


def _recommend(exp: Experiment, primary: MetricResult, srm_mismatch: bool, matured: int) -> tuple[str, str | None]:
    if srm_mismatch:
        return "check_srm", None
    if not primary.comparisons or matured < 100:
        return "collecting", None
    best = max(primary.comparisons, key=lambda c: c.prob_better)
    planned_reached = exp.planned_users is not None and matured >= exp.planned_users
    if best.prob_better >= exp.threshold:
        return "ship", best.variant
    if all(c.prob_better <= 1 - exp.threshold for c in primary.comparisons):
        return "keep_control", primary.variants[0].key
    return ("inconclusive" if planned_reached else "continue"), None


async def calculate(db: AsyncSession, principal: Principal, exp: Experiment) -> ExperimentResult:
    """Recalculates the experiment from the warehouse and stores a snapshot (row rules of the project apply)."""
    project = await db.get(Project, exp.project_id)
    assert project is not None
    source = await _source(db, exp)
    keys = [v["key"] for v in exp.variants]
    try:
        counts = await _agg(
            db, principal, source, project, metrics.assignment_counts_sql(exp.key, exp.assignments_table)
        )
        assigned = {str(r["variant"]): int(r["n"]) for r in counts}
        unknown = sorted(set(assigned) - set(keys))
        if unknown:
            raise ValidationFailed(f"В данных есть группы, которых нет в дизайне: {', '.join(unknown)}")
        srm = stats.srm([assigned.get(k, 0) for k in keys], [float(v["weight"]) for v in exp.variants])
        primary, segments = await _metric_result(db, principal, source, project, exp, exp.metric_key, True)
        secondary = [
            (await _metric_result(db, principal, source, project, exp, m, False))[0]
            for m in exp.secondary_metrics
            if m != exp.metric_key
        ]
    except Exception as exc:
        exp.last_error = getattr(exc, "message", None) or str(exc)
        raise
    matured = sum(v.n for v in primary.variants)
    recommendation, best = _recommend(exp, primary, srm.mismatch, matured)
    firsts = [r["first_at"] for r in counts if r["first_at"] is not None]
    lasts = [r["last_at"] for r in counts if r["last_at"] is not None]
    result = ExperimentResult(
        calculated_at=datetime.now(UTC),
        assigned={k: assigned.get(k, 0) for k in keys},
        matured_users=matured,
        progress=matured / exp.planned_users if exp.planned_users else None,
        primary=primary,
        secondary=secondary,
        segments=segments,
        srm=SrmOut(p_value=srm.p_value, observed=srm.observed, expected=srm.expected, mismatch=srm.mismatch),
        recommendation=recommendation,
        best_variant=best,
        first_assigned_at=min(firsts) if firsts else None,
        last_assigned_at=max(lasts) if lasts else None,
    )
    head = max(primary.comparisons, key=lambda c: c.prob_better) if primary.comparisons else None
    payload = result.model_dump(mode="json")
    exp.last_result, exp.last_calculated_at, exp.last_error = payload, result.calculated_at, ""
    db.add(
        ExperimentSnapshot(
            experiment_id=exp.id,
            calculated_at=result.calculated_at,
            users=matured,
            prob_best=head.prob_better if head else None,
            lift=head.lift if head else None,
            result=payload,
        )
    )
    await db.flush()
    return result


async def recalculate_all(db: AsyncSession) -> int:
    """Beat job: recalculates every running experiment as a system principal (data rules of projects still apply)."""
    running = list((await db.execute(select(Experiment).where(Experiment.status == "running"))).scalars())
    done = 0
    for exp in running:
        try:
            await calculate(db, system_principal(exp.org_id, "experiments"), exp)
            done += 1
        except Exception as exc:  # one broken experiment must not stop the others
            log.warning("experiment recalculation failed", experiment=exp.key, error=str(exc))
        await db.commit()
    return done


# ---------------------------------------------------------------- planning helpers
async def baseline(
    db: AsyncSession, principal: Principal, project: Project, source: DataSource, metric_key: str, window_days: int = 28
) -> dict[str, Any]:
    tpl = metrics.get_template(metric_key)
    rows = await _agg(db, principal, source, project, metrics.baseline_sql(metric_key, window_days))
    g = _group(rows[0]) if rows and rows[0]["n"] else stats.GroupStats(0, 0.0, 0.0)
    return {
        "metric_key": metric_key,
        "metric_type": tpl.type,
        "baseline": g.mean,
        "sd": math.sqrt(g.var),
        "daily_users": g.n / window_days,
        "users": g.n,
        "window_days": window_days,
    }


def assign(exp: Experiment, user_id: str) -> str | None:
    if exp.status != "running":
        return None
    return splitter.assign(
        exp.key, user_id, [(v["key"], float(v["weight"])) for v in exp.variants], exp.traffic_share, exp.salt
    )


# ---------------------------------------------------------------- knowledge base
def _pct(x: float) -> str:
    return f"{x * 100:+.1f}%"


def _fmt(value: float, unit: str) -> str:
    if unit == "%":
        return f"{value * 100:.2f}%"
    if unit == "$":
        return f"${value:.3f}"
    return f"{value:.3f}"


def report_markdown(exp: Experiment) -> str:
    res = ExperimentResult.model_validate(exp.last_result) if exp.last_result else None
    variants = ", ".join(f"{v['key']} — {v.get('name') or v['key']} ({v['weight'] * 100:.0f}%)" for v in exp.variants)
    lines = [
        "## Гипотеза",
        exp.hypothesis or "—",
        "",
        "## Дизайн",
        f"- Первичная метрика: {metrics.get_template(exp.metric_key).name}",
        f"- Защитные метрики: {', '.join(metrics.get_template(m).name for m in exp.secondary_metrics) or '—'}",
        f"- Группы и доли трафика: {variants}; трафик {exp.traffic_share * 100:.0f}%",
        f"- Сегменты: {', '.join(exp.segments) or '—'}",
        f"- Критерий остановки: P(лучше контроля) ≥ {exp.threshold:.2f}; MDE {exp.mde * 100:.1f}%",
        f"- Период: {exp.started_at:%Y-%m-%d} — {exp.ended_at:%Y-%m-%d}" if exp.started_at and exp.ended_at else "",
        "",
        "## Результат",
    ]
    if res:
        lines += [
            "| Метрика | Группа | Пользователей | Значение | Lift | P(лучше контроля) |",
            "|---|---|---|---|---|---|",
        ]
        for m in [res.primary, *res.secondary]:
            comps = {c.variant: c for c in m.comparisons}
            for v in m.variants:
                c = comps.get(v.key)
                lift = f"{_pct(c.lift)} [{_pct(c.lift_ci[0])}; {_pct(c.lift_ci[1])}]" if c else "—"
                prob = f"{c.prob_better:.3f}" if c else "контроль"
                lines.append(f"| {m.name} | {v.key} | {v.n:,} | {_fmt(v.mean, m.unit)} | {lift} | {prob} |")
        lines += [
            "",
            f"SRM: p = {res.srm.p_value:.4f}" + (" — **дисбаланс групп!**" if res.srm.mismatch else " (норма)"),
        ]
    else:
        lines.append("Результаты не рассчитаны.")
    lines += ["", "## Вывод и решение", exp.conclusion or "—"]
    return "\n".join(line for line in lines if line is not None)


async def save_to_kb(db: AsyncSession, principal: Principal, exp: Experiment) -> uuid.UUID:
    principal.require(P.KB_WRITE, exp.project_id)
    if exp.status not in ("completed", "archived") or not exp.decision:
        raise ConflictError("В базу знаний сохраняется завершённый эксперимент с принятым решением")
    if exp.kb_item_id is not None:
        raise ConflictError("Эксперимент уже сохранён в базе знаний")
    item = await kb_service.create_item(
        db,
        principal,
        org_id=exp.org_id,
        project_id=exp.project_id,
        type="experiment",
        title=exp.name,
        summary=exp.conclusion.split("\n", 1)[0][:2000],
        body=report_markdown(exp),
        tags=["ab", exp.metric_key.replace("_", "-")],
        links=[{"kind": "experiment", "ref": str(exp.id), "title": exp.key}]
        + ([{"kind": "event", "ref": exp.event_name, "title": exp.event_name}] if exp.event_name else []),
        decision=KB_DECISION.get(exp.decision, ""),
        source_ref=f"experiment:{exp.id}",
    )
    exp.kb_item_id = item.id
    await db.flush()
    return item.id
