"""Registry of demo-content hooks: modules add their seeding function here (keeps IAM decoupled)."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

from sqlalchemy.ext.asyncio import AsyncSession

if TYPE_CHECKING:
    from app.modules.iam.models import Organization, Project, User

DemoHook = Callable[[AsyncSession, "Organization", dict[str, "Project"], "User"], Awaitable[None]]
_HOOKS: list[DemoHook] = []


def demo_hook(fn: DemoHook) -> DemoHook:
    _HOOKS.append(fn)
    return fn


async def run_demo_hooks(db: AsyncSession, org: Organization, projects: dict[str, Project], admin: User) -> None:
    for hook in _HOOKS:
        await hook(db, org, projects, admin)
