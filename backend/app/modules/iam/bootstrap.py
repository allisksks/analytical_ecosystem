"""First-start provisioning: the organisation, the first administrator and (optionally) demo content."""

from __future__ import annotations

from dataclasses import dataclass

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.modules.audit.service import record
from app.modules.iam.models import Organization, Project, User
from app.modules.iam.service import create_organization, create_user, ensure_builtin_roles, grant

log = structlog.get_logger("bootstrap")


@dataclass(frozen=True)
class DemoProject:
    key: str
    name: str
    group: str
    app_id: str


DEMO_PROJECTS = (
    DemoProject("iron_shells", "Iron Shells", "1. Midcore", "iron_shells"),
    DemoProject("bloom_merge", "Bloom & Merge", "2. Casual / Puzzle", "bloom_merge"),
    DemoProject("drift_kings", "Drift Kings", "3. Hyper-Casual", "drift_kings"),
)

# (email local part, display name, role, projects or None for organisation-wide)
DEMO_USERS: tuple[tuple[str, str, str, tuple[str, ...] | None], ...] = (
    ("lead", "Мария Руководитель", "analytics_lead", None),
    ("analyst", "Алиса Аналитик", "analyst", ("iron_shells", "bloom_merge")),
    ("engineer", "Денис Инженер", "data_engineer", ("iron_shells", "bloom_merge", "drift_kings")),
    ("dev", "Павел Разработчик", "developer", ("iron_shells",)),
    ("product", "Ольга Продукт", "product", ("iron_shells",)),
    ("marketing", "Игорь Маркетинг", "marketing", ("drift_kings",)),
    ("ceo", "Сергей CEO", "executive", None),
)


async def bootstrap(db: AsyncSession) -> None:
    settings = get_settings()
    org = (await db.execute(select(Organization).order_by(Organization.created_at).limit(1))).scalar_one_or_none()
    if org is not None:
        await ensure_builtin_roles(db, org.id)
        await db.commit()
        return
    if settings.bootstrap_admin_password is None:
        log.warning("no users yet: set BOOTSTRAP_ADMIN_PASSWORD to create the first administrator")
        return
    org = await create_organization(db, "Demo Studio" if settings.bootstrap_demo else "Организация", "default")
    roles = await ensure_builtin_roles(db, org.id)
    admin = await create_user(
        db,
        org.id,
        settings.bootstrap_admin_email,
        "Администратор",
        settings.bootstrap_admin_password.get_secret_value(),
    )
    await grant(db, admin, roles["admin"], None)
    await record(
        db, "bootstrap.admin_created", org_id=org.id, actor_label="system", resource_type="user", resource_id=admin.id
    )
    if settings.bootstrap_demo:
        await _bootstrap_demo(db, org, roles, admin)
    await db.commit()
    log.info("bootstrap complete", admin=admin.email, demo=settings.bootstrap_demo)


async def _bootstrap_demo(db: AsyncSession, org: Organization, roles: dict, admin: User) -> None:  # type: ignore[type-arg]
    settings = get_settings()
    projects: dict[str, Project] = {}
    for dp in DEMO_PROJECTS:
        p = Project(org_id=org.id, key=dp.key, name=dp.name, group_name=dp.group, data_scope={"app_id": [dp.app_id]})
        db.add(p)
        projects[dp.key] = p
    await db.flush()
    domain = settings.bootstrap_admin_email.split("@", 1)[1] if "@" in settings.bootstrap_admin_email else "demo.local"
    password = settings.bootstrap_demo_password.get_secret_value()
    for local, name, role_key, scope in DEMO_USERS:
        user = await create_user(db, org.id, f"{local}@{domain}", name, password, check_strength=False)
        if scope is None:
            await grant(db, user, roles[role_key], None)
        else:
            for key in scope:
                await grant(db, user, roles[role_key], projects[key])
    # hooks of other modules (data sources, metrics, dashboards…) register here
    from app.modules.iam.demo_hooks import run_demo_hooks

    await run_demo_hooks(db, org, projects, admin)


async def user_count(db: AsyncSession) -> int:
    return int(await db.scalar(select(func.count()).select_from(User)) or 0)
