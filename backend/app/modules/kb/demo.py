from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.iam.demo_hooks import demo_hook
from app.modules.iam.models import Organization, Project, User
from app.modules.kb.service import install_examples


@demo_hook
async def demo_kb(db: AsyncSession, org: Organization, projects: dict[str, Project], admin: User) -> None:
    await install_examples(db, org.id, projects)
