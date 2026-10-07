"""A/B experiments API: designer and power calculator, lifecycle, results, assignment for SDKs."""

from __future__ import annotations

import contextlib
import uuid

from fastapi import APIRouter, Response
from sqlalchemy import select

from app.core.errors import AppError, ValidationFailed
from app.modules.connectors.models import DataSource
from app.modules.connectors.service import source_allowed_in
from app.modules.experiments import metrics, service, stats
from app.modules.experiments.models import Experiment, ExperimentSnapshot
from app.modules.experiments.schemas import (
    AssignIn,
    AssignOut,
    BaselineOut,
    DecisionIn,
    ExperimentIn,
    ExperimentOut,
    ExperimentPatch,
    ExperimentResult,
    ExperimentSummary,
    MetricTemplateOut,
    PowerIn,
    PowerOut,
    SdkExperiment,
    SdkVariant,
    SnapshotOut,
    TransitionIn,
)
from app.modules.iam.deps import DB, CurrentPrincipal
from app.modules.iam.models import Project
from app.modules.iam.permissions import P
from app.modules.iam.policy import Principal
from app.modules.query.service import load_project

router = APIRouter(prefix="/experiments", tags=["experiments"])


async def _project(db: DB, principal: Principal, project_id: uuid.UUID) -> Project:
    project = await load_project(db, principal, project_id)
    assert project is not None
    return project


def _summary(exp: Experiment) -> ExperimentSummary:
    s = ExperimentSummary.model_validate(exp)
    res = exp.last_result
    if res:
        comps = res["primary"]["comparisons"]
        head = max(comps, key=lambda c: c["prob_better"]) if comps else None
        s.prob_best = head["prob_better"] if head else None
        s.lift = head["lift"] if head else None
        s.users = res["matured_users"]
        s.recommendation = res["recommendation"]
        s.srm_mismatch = res["srm"]["mismatch"]
    return s


async def _out(db: DB, exp: Experiment) -> ExperimentOut:
    history = (
        await db.execute(
            select(ExperimentSnapshot)
            .where(ExperimentSnapshot.experiment_id == exp.id)
            .order_by(ExperimentSnapshot.calculated_at)
        )
    ).scalars()
    base = _summary(exp).model_dump()
    fields = set(ExperimentOut.model_fields) - set(base) - {"result", "history", "results_hidden"}
    return ExperimentOut(
        **base,
        **{f: getattr(exp, f) for f in fields},
        result=ExperimentResult.model_validate(exp.last_result) if exp.last_result else None,
        history=[SnapshotOut.model_validate(h) for h in history],
    )


# ---------------------------------------------------------------- planning
@router.get("/metrics", response_model=list[MetricTemplateOut], summary="Metric templates for experiments")
async def metric_templates(_: CurrentPrincipal) -> list[MetricTemplateOut]:
    return [
        MetricTemplateOut(
            key=m.key,
            name=m.name,
            type=m.type,
            days=m.days,
            unit=m.unit,
            description=m.description,
            semantic_keys=list(m.semantic_keys),
        )
        for m in metrics.TEMPLATES.values()
    ]


@router.post("/power", response_model=PowerOut, summary="Sample size and duration calculator")
async def power(body: PowerIn, _: CurrentPrincipal) -> PowerOut:
    try:
        res = stats.sample_size(
            body.metric_type,
            body.baseline,
            body.mde,
            sd=body.sd,
            alpha=body.alpha,
            power=body.power,
            groups=body.groups,
            daily_users=body.daily_users,
            traffic_share=body.traffic_share,
        )
    except ValueError as exc:
        raise ValidationFailed(str(exc)) from exc
    return PowerOut(per_group=res.per_group, total=res.total, days=res.days)


@router.get("/baseline", response_model=BaselineOut, summary="Current value of a metric over recent matured installs")
async def metric_baseline(
    principal: CurrentPrincipal, db: DB, project_id: uuid.UUID, source_id: uuid.UUID, metric_key: str
) -> BaselineOut:
    project = await _project(db, principal, project_id)
    if not (principal.can(P.EXPERIMENTS_PROPOSE, project.id) or principal.can(P.EXPERIMENTS_EDIT, project.id)):
        principal.require(P.EXPERIMENTS_PROPOSE, project.id)
    source = await db.get(DataSource, source_id)
    if source is None or source.org_id != principal.org_id or not source_allowed_in(source, project.id):
        raise ValidationFailed("Источник не найден или не подключён к проекту")
    return BaselineOut(**await service.baseline(db, principal, project, source, metric_key))


# ---------------------------------------------------------------- SDK
@router.get("/sdk-config", response_model=list[SdkExperiment], summary="Running experiments for client-side splitting")
async def sdk_config(principal: CurrentPrincipal, db: DB, project_id: uuid.UUID) -> list[SdkExperiment]:
    project = await _project(db, principal, project_id)
    principal.require(P.EXPERIMENTS_VIEW, project.id)
    q = select(Experiment).where(
        Experiment.project_id == project.id, Experiment.status == "running", Experiment.splitter == "internal"
    )
    return [
        SdkExperiment(
            key=e.key,
            salt=e.salt,
            traffic_share=e.traffic_share,
            variants=[SdkVariant(key=v["key"], weight=v["weight"]) for v in e.variants],
        )
        for e in (await db.execute(q.order_by(Experiment.key))).scalars()
    ]


@router.post("/assign", response_model=AssignOut, summary="Deterministic variant of a user (internal splitter)")
async def assign(body: AssignIn, principal: CurrentPrincipal, db: DB) -> AssignOut:
    project = await _project(db, principal, body.project_id)
    principal.require(P.EXPERIMENTS_VIEW, project.id)
    exp = (
        await db.execute(
            select(Experiment).where(Experiment.project_id == project.id, Experiment.key == body.experiment_key)
        )
    ).scalar_one_or_none()
    if exp is None or exp.splitter != "internal":
        raise ValidationFailed("Эксперимент с внутренним сплиттером не найден")
    return AssignOut(experiment_key=exp.key, user_id=body.user_id, variant=service.assign(exp, body.user_id))


# ---------------------------------------------------------------- experiments
@router.get("", response_model=list[ExperimentSummary])
async def list_experiments(
    principal: CurrentPrincipal, db: DB, project_id: uuid.UUID, status: str | None = None
) -> list[ExperimentSummary]:
    project = await _project(db, principal, project_id)
    service.require_view(principal, project.id)
    q = select(Experiment).where(Experiment.project_id == project.id)
    if status:
        q = q.where(Experiment.status == status)
    items = (await db.execute(q.order_by(Experiment.updated_at.desc()))).scalars()
    return [_summary(e) for e in items if service.visible(principal, e)]


@router.post("", response_model=ExperimentOut, status_code=201)
async def create_experiment(body: ExperimentIn, principal: CurrentPrincipal, db: DB) -> ExperimentOut:
    project = await _project(db, principal, body.project_id)
    exp = await service.create(db, principal, project, body.model_dump())
    return await _out(db, exp)


@router.get("/{experiment_id}", response_model=ExperimentOut)
async def get_experiment(experiment_id: uuid.UUID, principal: CurrentPrincipal, db: DB) -> ExperimentOut:
    return await _out(db, await service.get_experiment(db, principal, experiment_id))


@router.patch("/{experiment_id}", response_model=ExperimentOut)
async def update_experiment(
    experiment_id: uuid.UUID, body: ExperimentPatch, principal: CurrentPrincipal, db: DB
) -> ExperimentOut:
    exp = await service.get_experiment(db, principal, experiment_id)
    await service.update(db, principal, exp, body.model_dump(exclude_unset=True))
    return await _out(db, exp)


@router.post(
    "/{experiment_id}/transition", response_model=ExperimentOut, summary="draft → review → running → completed"
)
async def transition(
    experiment_id: uuid.UUID, body: TransitionIn, principal: CurrentPrincipal, db: DB
) -> ExperimentOut:
    exp = await service.get_experiment(db, principal, experiment_id)
    await service.transition(db, principal, exp, body.to, body.comment)
    if body.to in ("running", "completed"):
        with contextlib.suppress(AppError):  # results right away; a data problem must not block the lifecycle
            await service.calculate(db, principal, exp)
    return await _out(db, exp)


@router.post("/{experiment_id}/recalculate", response_model=ExperimentOut)
async def recalculate(experiment_id: uuid.UUID, principal: CurrentPrincipal, db: DB) -> ExperimentOut:
    exp = await service.get_experiment(db, principal, experiment_id)
    principal.require(P.EXPERIMENTS_EDIT, exp.project_id)
    if exp.status not in ("running", "completed"):
        raise ValidationFailed("Результаты считаются для запущенных и завершённых экспериментов")
    try:
        await service.calculate(db, principal, exp)
    except AppError as exc:
        exp.last_error = exc.message
        await db.commit()
        raise
    return await _out(db, exp)


@router.post("/{experiment_id}/decision", response_model=ExperimentOut, summary="Final decision of the gatekeeper")
async def decide(experiment_id: uuid.UUID, body: DecisionIn, principal: CurrentPrincipal, db: DB) -> ExperimentOut:
    exp = await service.get_experiment(db, principal, experiment_id)
    await service.decide(db, principal, exp, body.decision, body.conclusion)
    return await _out(db, exp)


@router.post("/{experiment_id}/kb", response_model=ExperimentOut, summary="Save the result to the knowledge base")
async def save_to_kb(experiment_id: uuid.UUID, principal: CurrentPrincipal, db: DB) -> ExperimentOut:
    exp = await service.get_experiment(db, principal, experiment_id)
    await service.save_to_kb(db, principal, exp)
    return await _out(db, exp)


@router.get("/{experiment_id}/report.md", response_class=Response, summary="Markdown report")
async def report(experiment_id: uuid.UUID, principal: CurrentPrincipal, db: DB) -> Response:
    exp = await service.get_experiment(db, principal, experiment_id)
    md = f"# {exp.name}\n\n" + service.report_markdown(exp)
    return Response(
        md,
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{exp.key}.md"'},
    )
