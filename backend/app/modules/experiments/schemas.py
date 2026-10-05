from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import Field, field_validator

from app.core.schemas import Schema

Status = Literal["draft", "review", "running", "completed", "archived"]
Decision = Literal["ship", "keep_control", "inconclusive"]
Recommendation = Literal["collecting", "continue", "ship", "keep_control", "inconclusive", "check_srm"]


class VariantIn(Schema):
    key: str = Field(min_length=1, max_length=32, pattern=r"^[A-Za-z0-9_-]+$")
    name: str = ""
    weight: float = Field(default=0.5, gt=0, le=1)
    description: str = ""


class ExperimentIn(Schema):
    project_id: uuid.UUID
    key: str = Field(min_length=2, max_length=120, pattern=r"^[a-z0-9][a-z0-9_.-]*$")
    name: str = Field(min_length=1, max_length=300)
    hypothesis: str = ""
    description: str = ""
    owner: str = ""
    metric_key: str
    secondary_metrics: list[str] = Field(default_factory=list)
    variants: list[VariantIn] = Field(
        default_factory=lambda: [VariantIn(key="A", name="Контроль"), VariantIn(key="B", name="Тест")]
    )
    traffic_share: float = Field(default=1.0, gt=0, le=1)
    segments: list[str] = Field(default_factory=list)
    mde: float = Field(default=0.05, gt=0, lt=10)
    alpha: float = Field(default=0.05, gt=0, lt=0.5)
    power: float = Field(default=0.8, gt=0.5, lt=1)
    baseline: float | None = None
    planned_users: int | None = Field(default=None, gt=0)
    planned_days: int | None = Field(default=None, gt=0)
    threshold: float = Field(default=0.95, ge=0.8, lt=1)
    event_name: str = ""
    splitter: Literal["external", "internal"] = "external"
    source_id: uuid.UUID | None = None
    assignments_table: str = Field(default="ab_assignments", pattern=r"^[A-Za-z_][A-Za-z0-9_.]*$")

    @field_validator("variants")
    @classmethod
    def _variants(cls, v: list[VariantIn]) -> list[VariantIn]:
        if not 2 <= len(v) <= 6:
            raise ValueError("нужно от 2 до 6 групп")
        if len({x.key for x in v}) != len(v):
            raise ValueError("ключи групп должны быть уникальны")
        return v


class ExperimentPatch(Schema):
    name: str | None = None
    hypothesis: str | None = None
    description: str | None = None
    owner: str | None = None
    metric_key: str | None = None
    secondary_metrics: list[str] | None = None
    variants: list[VariantIn] | None = None
    traffic_share: float | None = Field(default=None, gt=0, le=1)
    segments: list[str] | None = None
    mde: float | None = Field(default=None, gt=0, lt=10)
    alpha: float | None = Field(default=None, gt=0, lt=0.5)
    power: float | None = Field(default=None, gt=0.5, lt=1)
    baseline: float | None = None
    planned_users: int | None = Field(default=None, gt=0)
    planned_days: int | None = Field(default=None, gt=0)
    threshold: float | None = Field(default=None, ge=0.8, lt=1)
    event_name: str | None = None
    splitter: Literal["external", "internal"] | None = None
    source_id: uuid.UUID | None = None
    assignments_table: str | None = Field(default=None, pattern=r"^[A-Za-z_][A-Za-z0-9_.]*$")


class TransitionIn(Schema):
    to: Status
    comment: str = ""


class DecisionIn(Schema):
    decision: Decision
    conclusion: str = Field(min_length=1)


# ---------------------------------------------------------------- results
class VariantStat(Schema):
    key: str
    n: int
    mean: float
    sd: float


class FrequentistOut(Schema):
    method: str
    p_value: float
    diff: float
    ci: list[float]  # [low, high]
    significant: bool


class Comparison(Schema):
    variant: str
    prob_better: float
    lift: float
    lift_ci: list[float]  # [low, high]
    expected_loss: float
    posterior_control: list[float]  # [mean, sd]
    posterior_variant: list[float]  # [mean, sd]
    method: str
    frequentist: FrequentistOut | None = None


class SrmOut(Schema):
    p_value: float
    observed: list[int]
    expected: list[float]
    mismatch: bool


class MetricResult(Schema):
    metric: str
    name: str
    type: str
    unit: str = ""
    variants: list[VariantStat]
    comparisons: list[Comparison]


class SegmentResult(Schema):
    segment: str
    value: str
    variants: list[VariantStat]
    comparisons: list[Comparison]
    srm_mismatch: bool = False


class ExperimentResult(Schema):
    calculated_at: datetime
    assigned: dict[str, int]
    matured_users: int
    progress: float | None  # matured users / planned users
    primary: MetricResult
    secondary: list[MetricResult] = Field(default_factory=list)
    segments: list[SegmentResult] = Field(default_factory=list)
    srm: SrmOut
    recommendation: Recommendation
    best_variant: str | None = None
    first_assigned_at: datetime | None = None
    last_assigned_at: datetime | None = None


class SnapshotOut(Schema):
    calculated_at: datetime
    users: int
    prob_best: float | None
    lift: float | None


# ---------------------------------------------------------------- experiments
class ExperimentSummary(Schema):
    id: uuid.UUID
    project_id: uuid.UUID
    key: str
    name: str
    owner: str
    status: Status
    metric_key: str
    variants: list[VariantIn]
    traffic_share: float
    started_at: datetime | None
    ended_at: datetime | None
    decision: str
    planned_users: int | None
    planned_days: int | None
    updated_at: datetime
    # headline of the last calculation
    prob_best: float | None = None
    lift: float | None = None
    users: int | None = None
    recommendation: str | None = None
    srm_mismatch: bool = False


class ExperimentOut(ExperimentSummary):
    hypothesis: str
    description: str
    secondary_metrics: list[str]
    segments: list[str]
    mde: float
    alpha: float
    power: float
    baseline: float | None
    threshold: float
    event_name: str
    splitter: str
    salt: str
    source_id: uuid.UUID | None
    assignments_table: str
    approved_by: str
    conclusion: str
    decided_by: str
    kb_item_id: uuid.UUID | None
    created_by: str
    created_at: datetime
    last_calculated_at: datetime | None
    last_error: str
    result: ExperimentResult | None = None
    history: list[SnapshotOut] = Field(default_factory=list)
    results_hidden: bool = False  # running experiment seen by a role with access to final results only


# ---------------------------------------------------------------- planning
class MetricTemplateOut(Schema):
    key: str
    name: str
    type: str
    days: int
    unit: str
    description: str
    semantic_keys: list[str]


class PowerIn(Schema):
    metric_type: Literal["binary", "continuous"]
    baseline: float
    mde: float = Field(gt=0, lt=10)
    sd: float | None = None
    alpha: float = Field(default=0.05, gt=0, lt=0.5)
    power: float = Field(default=0.8, gt=0.5, lt=1)
    groups: int = Field(default=2, ge=2, le=6)
    daily_users: float | None = Field(default=None, gt=0)
    traffic_share: float = Field(default=1.0, gt=0, le=1)


class PowerOut(Schema):
    per_group: int
    total: int
    days: int | None


class BaselineOut(Schema):
    metric_key: str
    metric_type: str
    baseline: float
    sd: float
    daily_users: float
    users: int
    window_days: int


class AssignIn(Schema):
    project_id: uuid.UUID
    experiment_key: str
    user_id: str = Field(min_length=1, max_length=200)


class AssignOut(Schema):
    experiment_key: str
    user_id: str
    variant: str | None  # None: user is outside the experiment traffic


class SdkVariant(Schema):
    key: str
    weight: float


class SdkExperiment(Schema):
    key: str
    salt: str
    traffic_share: float
    variants: list[SdkVariant]
