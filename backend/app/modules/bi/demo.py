from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.bi.service import create_from_template, templates
from app.modules.iam.demo_hooks import demo_hook
from app.modules.iam.models import Organization, Project, User


@demo_hook
async def demo_dashboards(db: AsyncSession, org: Organization, projects: dict[str, Project], admin: User) -> None:
    for i, tpl in enumerate(templates()):
        if tpl.get("scope") == "portfolio":
            await create_from_template(db, org.id, None, tpl, admin.id, i)
        else:
            for p in projects.values():
                await create_from_template(db, org.id, p, tpl, admin.id, i)
