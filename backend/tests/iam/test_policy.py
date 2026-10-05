from __future__ import annotations

import uuid

import pytest

from app.core.errors import PermissionDenied
from app.modules.iam.permissions import BUILTIN_BY_KEY, P
from app.modules.iam.policy import Principal

A, B = uuid.uuid4(), uuid.uuid4()


def make(org: set[str], projects: dict[uuid.UUID, set[str]]) -> Principal:
    return Principal(
        id=uuid.uuid4(),
        org_id=uuid.uuid4(),
        kind="user",
        label="x",
        org_permissions=frozenset(org),
        project_permissions={k: frozenset(v) for k, v in projects.items()},
        roles_by_project={None: ("r",)} if org else {k: ("r",) for k in projects},
    )


def test_project_role_applies_only_inside_project() -> None:
    p = make(set(), {A: set(BUILTIN_BY_KEY["analyst"].permissions)})
    assert p.can(P.SQL_RUN, A)
    assert not p.can(P.SQL_RUN, B)
    assert p.visible_project_ids() == {A}
    with pytest.raises(PermissionDenied):
        p.require(P.SQL_RUN, B)


def test_org_role_applies_to_every_project() -> None:
    p = make(set(BUILTIN_BY_KEY["executive"].permissions), {})
    assert p.can(P.DASHBOARDS_VIEW, A) and p.can(P.DASHBOARDS_VIEW, B)
    assert p.can(P.PORTFOLIO_VIEW)
    assert p.visible_project_ids() is None
    assert not p.can(P.SQL_RUN, A)


def test_org_level_permissions_are_not_granted_by_project_roles() -> None:
    p = make(set(), {A: {P.ADMIN_USERS, P.SQL_RUN_ALL, P.KB_VIEW}})
    assert not p.can(P.ADMIN_USERS, A)
    assert not p.can(P.SQL_RUN_ALL, A)
    assert p.can(P.KB_VIEW, A)
    assert p.projects_with(P.KB_VIEW) == {A}


def test_builtin_roles_match_tz_table() -> None:
    assert P.CONNECTORS_MANAGE in BUILTIN_BY_KEY["admin"].permissions
    assert P.CONNECTORS_MANAGE not in BUILTIN_BY_KEY["data_engineer"].permissions
    assert P.EVENTS_APPROVE in BUILTIN_BY_KEY["analytics_lead"].permissions
    assert P.EVENTS_APPROVE not in BUILTIN_BY_KEY["analyst"].permissions
    assert BUILTIN_BY_KEY["developer"].permissions >= {P.EVENTS_DOWNLOAD, P.EVENTS_COMMENT}
    assert P.SQL_RUN not in BUILTIN_BY_KEY["product"].permissions
    assert P.KB_ASK in BUILTIN_BY_KEY["product"].permissions
    assert BUILTIN_BY_KEY["guest"].permissions == {P.DASHBOARDS_VIEW_SHARED}
    assert P.PII_VIEW not in BUILTIN_BY_KEY["analyst"].permissions
