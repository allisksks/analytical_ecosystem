"""Registry of demo-content hooks: modules add their seeding function here (keeps IAM decoupled)."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

from sqlalchemy.ext.asyncio import AsyncSession

if TYPE_CHECKING:
    from app.modules.iam.models import Organization, Project, User

DemoHook = Callable[[AsyncSession, "Organization", dict[str, "Project"], "User"], Awaitable[None]]
_HOOKS: list[tuple[int, DemoHook]] = []


def demo_hook(fn: DemoHook) -> DemoHook:
    _HOOKS.append((50, fn))
    return fn


def demo_hook_late(fn: DemoHook) -> DemoHook:
    """For content built on top of other modules' demo content (sources, knowledge base…)."""
    _HOOKS.append((90, fn))
    return fn


async def run_demo_hooks(db: AsyncSession, org: Organization, projects: dict[str, Project], admin: User) -> None:
    import app.modules.demo  # noqa: F401  (registers hooks of every module)

    for _, hook in sorted(_HOOKS, key=lambda h: h[0]):  # stable: same order keeps registration order
        await hook(db, org, projects, admin)
