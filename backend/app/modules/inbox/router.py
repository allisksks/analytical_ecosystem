"""Inbox: tasks waiting for the principal in a project — only those their permissions let them act on."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from fastapi import APIRouter
from sqlalchemy import func, select

from app.core.schemas import Schema
from app.modules.ems.models import Alert, Event, EventVersion, TrackingDraft, TrackingDraftItem
from app.modules.experiments.models import Experiment
from app.modules.iam.deps import DB, CurrentPrincipal
from app.modules.iam.permissions import P
from app.modules.query.service import load_project

router = APIRouter(prefix="/inbox", tags=["inbox"])
Kind = Literal["event_review", "ai_drafts", "alert", "experiment_review", "experiment_decision", "experiment_ready"]


class Task(Schema):
    kind: Kind
    title: str
    subtitle: str = ""
    link: str
    severity: Literal["info", "warning", "critical"] = "info"
    at: datetime | None = None


class Counts(Schema):
    event_reviews: int = 0
    ai_drafts: int = 0
    alerts: int = 0
    experiment_reviews: int = 0
    experiment_decisions: int = 0

    @property
    def total(self) -> int:
        return sum(self.model_dump().values())


class InboxOut(Schema):
    counts: Counts
    total: int
    tasks: list[Task]


@router.get("", response_model=InboxOut, summary="Tasks waiting for me in a project")
async def inbox(principal: CurrentPrincipal, db: DB, project_id: uuid.UUID) -> InboxOut:
    project = await load_project(db, principal, project_id)
    assert project is not None
    pid, can = project.id, principal.can
    counts, tasks = Counts(), list[Task]()

    if can(P.EVENTS_APPROVE, pid):
        rows = (
            await db.execute(
                select(Event.name, EventVersion.version, EventVersion.author, EventVersion.created_at)
                .join(EventVersion, EventVersion.event_id == Event.id)
                .where(Event.project_id == pid, EventVersion.status == "pending")
                .order_by(EventVersion.created_at)
            )
        ).all()
        counts.event_reviews = len(rows)
        tasks += [
            Task(kind="event_review", title=f"{name} v{version}", subtitle=author, link=f"/ems?event={name}", at=at)
            for name, version, author, at in rows
        ]

    if can(P.EVENTS_EDIT, pid):
        drafts = (
            await db.execute(
                select(TrackingDraft.id, TrackingDraft.title, TrackingDraft.created_at, func.count())
                .join(TrackingDraftItem, TrackingDraftItem.draft_id == TrackingDraft.id)
                .where(TrackingDraft.project_id == pid, TrackingDraftItem.status == "pending")
                .group_by(TrackingDraft.id)
                .order_by(TrackingDraft.created_at.desc())
            )
        ).all()
        counts.ai_drafts = sum(int(n) for _, _, _, n in drafts)
        tasks += [
            Task(kind="ai_drafts", title=title, subtitle=str(int(n)), at=at, link=f"/ems?tab=aiDrafts&draft={did}")
            for did, title, at, n in drafts
        ]

    if can(P.EVENTS_VIEW, pid):
        alerts = (
            await db.execute(
                select(Alert)
                .where(Alert.project_id == pid, Alert.status == "open")
                .order_by(Alert.severity.desc(), Alert.last_seen_at.desc())
            )
        ).scalars()
        for a in alerts:
            counts.alerts += 1
            tasks.append(
                Task(
                    kind="alert",
                    title=a.title,
                    subtitle=a.event_name,
                    link="/ems?tab=alerts",
                    severity="critical" if a.severity == "critical" else "warning",
                    at=a.last_seen_at,
                )
            )

    if can(P.EXPERIMENTS_VIEW, pid):
        exps = (
            await db.execute(
                select(Experiment).where(
                    Experiment.project_id == pid, Experiment.status.in_(("review", "running", "completed"))
                )
            )
        ).scalars()
        for e in exps:
            rec = (e.last_result or {}).get("recommendation")
            if e.status == "review" and can(P.EXPERIMENTS_APPROVE, pid):
                counts.experiment_reviews += 1
                tasks.append(
                    Task(kind="experiment_review", title=e.name, subtitle=e.owner, link=f"/ab/{e.id}", at=e.updated_at)
                )
            elif e.status == "completed" and not e.decision and can(P.EXPERIMENTS_APPROVE, pid):
                counts.experiment_decisions += 1
                tasks.append(
                    Task(kind="experiment_decision", title=e.name, subtitle=e.owner, link=f"/ab/{e.id}", at=e.ended_at)
                )
            elif (
                e.status == "running" and rec in ("ship", "keep_control", "check_srm") and can(P.EXPERIMENTS_EDIT, pid)
            ):
                counts.experiment_decisions += 1
                tasks.append(
                    Task(
                        kind="experiment_ready",
                        title=e.name,
                        subtitle=str(rec),
                        link=f"/ab/{e.id}",
                        severity="warning" if rec == "check_srm" else "info",
                        at=e.last_calculated_at,
                    )
                )

    order = {"critical": 0, "warning": 1, "info": 2}
    tasks.sort(key=lambda t: (order[t.severity], -(t.at.timestamp() if t.at else 0)))
    return InboxOut(counts=counts, total=counts.total, tasks=tasks[:50])
