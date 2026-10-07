"""Policy module: the single place that decides "may <principal> do <permission> in <project>".

Effective permissions in a project = union of the user's organisation-wide roles and the roles
granted in that project. Organisation-level permissions (admin:*, portfolio:view, sql:run_all)
are taken only from organisation-wide roles.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from app.core.errors import PermissionDenied
from app.modules.iam.permissions import ADMIN_PERMISSIONS, ORG_LEVEL


@dataclass(frozen=True)
class Principal:
    id: uuid.UUID
    org_id: uuid.UUID
    kind: str  # "user" | "token"
    label: str  # email or token name
    org_permissions: frozenset[str]
    project_permissions: dict[uuid.UUID, frozenset[str]] = field(default_factory=dict)
    roles_by_project: dict[uuid.UUID | None, tuple[str, ...]] = field(default_factory=dict)
    ip: str = ""

    def permissions_in(self, project_id: uuid.UUID | None) -> frozenset[str]:
        if project_id is None:
            return self.org_permissions
        scoped = self.project_permissions.get(project_id, frozenset())
        return (self.org_permissions - ORG_LEVEL) | (scoped - ORG_LEVEL) | (self.org_permissions & ORG_LEVEL)

    def can(self, permission: str, project_id: uuid.UUID | None = None) -> bool:
        return permission in self.permissions_in(project_id)

    def require(self, permission: str, project_id: uuid.UUID | None = None) -> None:
        if not self.can(permission, project_id):
            raise PermissionDenied(
                "Недостаточно прав", details={"permission": permission, "project_id": str(project_id or "")}
            )

    def can_anywhere(self, permission: str) -> bool:
        return permission in self.org_permissions or any(permission in p for p in self.project_permissions.values())

    def visible_project_ids(self) -> set[uuid.UUID] | None:
        """Projects the principal belongs to; ``None`` means "all projects" (organisation-wide role)."""
        if self.roles_by_project.get(None):
            return None
        return set(self.project_permissions)

    def projects_with(self, permission: str) -> set[uuid.UUID] | None:
        """Projects where the permission holds; ``None`` = in every project of the organisation."""
        if permission in self.org_permissions:
            return None
        return {pid for pid, perms in self.project_permissions.items() if permission in perms}

    @property
    def is_admin(self) -> bool:
        return bool(self.org_permissions & ADMIN_PERMISSIONS)
