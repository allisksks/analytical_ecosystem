"""Writing to the audit journal. Every entry is also emitted to the structured log (Loki / SIEM via syslog)."""

from __future__ import annotations

import uuid
from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.audit.models import AuditLog
from app.modules.iam.policy import Principal

log = structlog.get_logger("audit")


async def record(
    db: AsyncSession,
    action: str,
    *,
    principal: Principal | None = None,
    org_id: uuid.UUID | None = None,
    actor_label: str = "",
    resource_type: str = "",
    resource_id: str | uuid.UUID = "",
    project_id: uuid.UUID | None = None,
    outcome: str = "success",
    sql: str | None = None,
    row_count: int | None = None,
    ip: str = "",
    details: dict[str, Any] | None = None,
) -> None:
    entry = AuditLog(
        org_id=principal.org_id if principal else org_id,
        actor_id=principal.id if principal else None,
        actor_type=principal.kind if principal else "system",
        actor_label=principal.label if principal else actor_label,
        action=action,
        resource_type=resource_type,
        resource_id=str(resource_id),
        project_id=project_id,
        outcome=outcome,
        ip=ip or (principal.ip if principal else ""),
        sql=sql,
        row_count=row_count,
        details=details or {},
    )
    db.add(entry)
    log.info(
        action,
        actor=entry.actor_label,
        actor_type=entry.actor_type,
        resource=f"{resource_type}:{resource_id}" if resource_type else "",
        project_id=str(project_id) if project_id else None,
        outcome=outcome,
        row_count=row_count,
    )
