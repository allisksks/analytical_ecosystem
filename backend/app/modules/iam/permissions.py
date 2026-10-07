"""Permission vocabulary and the built-in roles from the TZ (section 2).

A permission is ``"<resource>:<action>"``. Roles are sets of permissions; an administrator can create
custom roles from the same vocabulary. Every API endpoint checks one permission in a project scope.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class P(StrEnum):
    # connectors & catalog
    CONNECTORS_VIEW = "connectors:view"
    CONNECTORS_CONFIGURE = "connectors:configure"  # change settings of existing sources
    CONNECTORS_MANAGE = "connectors:manage"  # create sources and see/replace secrets
    CATALOG_VIEW = "catalog:view"
    CATALOG_EDIT = "catalog:edit"
    # semantic layer
    SEMANTIC_VIEW = "semantic:view"
    SEMANTIC_EDIT = "semantic:edit"
    # event registry
    EVENTS_VIEW = "events:view"
    EVENTS_COMMENT = "events:comment"
    EVENTS_DOWNLOAD = "events:download"
    EVENTS_EDIT = "events:edit"  # create drafts
    EVENTS_APPROVE = "events:approve"
    # experiments
    EXPERIMENTS_VIEW = "experiments:view"
    EXPERIMENTS_RESULTS = "experiments:results"  # see final results only
    EXPERIMENTS_PROPOSE = "experiments:propose"
    EXPERIMENTS_EDIT = "experiments:edit"
    EXPERIMENTS_APPROVE = "experiments:approve"
    # dashboards
    DASHBOARDS_VIEW = "dashboards:view"
    DASHBOARDS_VIEW_SHARED = "dashboards:view_shared"
    DASHBOARDS_EDIT_OWN = "dashboards:edit_own"
    DASHBOARDS_EDIT = "dashboards:edit"
    DASHBOARDS_MARTS = "dashboards:marts"
    PORTFOLIO_VIEW = "portfolio:view"
    # SQL
    SQL_RUN = "sql:run"  # sources of own projects
    SQL_RUN_ALL = "sql:run_all"  # any source of the organisation
    PII_VIEW = "pii:view"  # see unmasked personal data columns
    # knowledge base & assistant
    KB_VIEW = "kb:view"
    KB_ASK = "kb:ask"
    KB_WRITE = "kb:write"
    KB_MODERATE = "kb:moderate"
    AI_SQL = "ai:sql"
    # administration
    ADMIN_USERS = "admin:users"
    ADMIN_ROLES = "admin:roles"
    ADMIN_PROJECTS = "admin:projects"
    ADMIN_AUDIT = "admin:audit"
    ADMIN_TOKENS = "admin:tokens"


ALL_PERMISSIONS: frozenset[str] = frozenset(p.value for p in P)

# Permissions that only make sense organisation-wide (not inside a single project).
ORG_LEVEL: frozenset[str] = frozenset(
    {P.ADMIN_USERS, P.ADMIN_ROLES, P.ADMIN_PROJECTS, P.ADMIN_AUDIT, P.ADMIN_TOKENS, P.SQL_RUN_ALL, P.PORTFOLIO_VIEW}
)

# Roles holding any of these must use a second factor (TZ: 2FA is mandatory for administrators).
ADMIN_PERMISSIONS: frozenset[str] = frozenset({P.ADMIN_USERS, P.ADMIN_ROLES, P.CONNECTORS_MANAGE})


@dataclass(frozen=True)
class BuiltinRole:
    key: str
    name_ru: str
    name_en: str
    description: str
    permissions: frozenset[str]


_READ_ALL = {
    P.CONNECTORS_VIEW,
    P.CATALOG_VIEW,
    P.SEMANTIC_VIEW,
    P.EVENTS_VIEW,
    P.EXPERIMENTS_VIEW,
    P.EXPERIMENTS_RESULTS,
    P.DASHBOARDS_VIEW,
    P.KB_VIEW,
}

BUILTIN_ROLES: tuple[BuiltinRole, ...] = (
    BuiltinRole(
        "admin",
        "Администратор платформы",
        "Platform administrator",
        "CTO, DevOps: создаёт коннекторы и хранит секреты, управляет пользователями и ролями",
        frozenset(
            {
                *_READ_ALL,
                P.CONNECTORS_CONFIGURE,
                P.CONNECTORS_MANAGE,
                P.SQL_RUN,
                P.SQL_RUN_ALL,
                P.ADMIN_USERS,
                P.ADMIN_ROLES,
                P.ADMIN_PROJECTS,
                P.ADMIN_AUDIT,
                P.ADMIN_TOKENS,
                P.CATALOG_EDIT,
                P.PORTFOLIO_VIEW,
            }
        ),
    ),
    BuiltinRole(
        "data_engineer",
        "Инженер данных",
        "Data engineer",
        "Настраивает коннекторы, редактирует реестр и витрины, SQL по всем источникам проекта",
        frozenset(
            {
                *_READ_ALL,
                P.CONNECTORS_CONFIGURE,
                P.CATALOG_EDIT,
                P.SEMANTIC_EDIT,
                P.EVENTS_EDIT,
                P.EVENTS_COMMENT,
                P.EVENTS_DOWNLOAD,
                P.DASHBOARDS_EDIT,
                P.DASHBOARDS_MARTS,
                P.SQL_RUN,
                P.PII_VIEW,
            }
        ),
    ),
    BuiltinRole(
        "analytics_lead",
        "Руководитель аналитики",
        "Head of analytics",
        "Гейткипер: утверждает версии событий, запуск и итог экспериментов, модерирует базу знаний",
        frozenset(
            {
                *_READ_ALL,
                P.CATALOG_EDIT,
                P.SEMANTIC_EDIT,
                P.EVENTS_EDIT,
                P.EVENTS_APPROVE,
                P.EVENTS_COMMENT,
                P.EVENTS_DOWNLOAD,
                P.EXPERIMENTS_PROPOSE,
                P.EXPERIMENTS_EDIT,
                P.EXPERIMENTS_APPROVE,
                P.DASHBOARDS_EDIT,
                P.DASHBOARDS_EDIT_OWN,
                P.SQL_RUN,
                P.KB_ASK,
                P.KB_WRITE,
                P.KB_MODERATE,
                P.AI_SQL,
                P.PORTFOLIO_VIEW,
            }
        ),
    ),
    BuiltinRole(
        "analyst",
        "Аналитик",
        "Analyst",
        "Создаёт черновики событий, ведёт эксперименты, редактирует дашборды, пишет SQL в своих проектах",
        frozenset(
            {
                *_READ_ALL,
                P.CATALOG_EDIT,
                P.EVENTS_EDIT,
                P.EVENTS_COMMENT,
                P.EVENTS_DOWNLOAD,
                P.EXPERIMENTS_PROPOSE,
                P.EXPERIMENTS_EDIT,
                P.DASHBOARDS_EDIT,
                P.DASHBOARDS_EDIT_OWN,
                P.SQL_RUN,
                P.KB_ASK,
                P.KB_WRITE,
                P.AI_SQL,
            }
        ),
    ),
    BuiltinRole(
        "developer",
        "Разработчик",
        "Developer",
        "Разработчик SDK клиента: читает и комментирует события, скачивает схемы, читает конфиг экспериментов",
        frozenset({P.EVENTS_VIEW, P.EVENTS_COMMENT, P.EVENTS_DOWNLOAD, P.EXPERIMENTS_VIEW, P.KB_VIEW}),
    ),
    BuiltinRole(
        "product",
        "Продукт",
        "Product",
        "Product Owner, геймдизайнер: свои дашборды, конструктор когорт, предлагает гипотезы, спрашивает ассистента",
        frozenset(
            {
                P.EVENTS_VIEW,
                P.EXPERIMENTS_VIEW,
                P.EXPERIMENTS_RESULTS,
                P.EXPERIMENTS_PROPOSE,
                P.DASHBOARDS_VIEW,
                P.DASHBOARDS_EDIT_OWN,
                P.SEMANTIC_VIEW,
                P.KB_VIEW,
                P.KB_ASK,
            }
        ),
    ),
    BuiltinRole(
        "marketing",
        "Маркетинг",
        "Marketing",
        "UA-менеджер: витрина привлечения, просмотр событий и экспериментов, чтение базы знаний",
        frozenset(
            {
                P.EVENTS_VIEW,
                P.EXPERIMENTS_VIEW,
                P.EXPERIMENTS_RESULTS,
                P.DASHBOARDS_VIEW,
                P.DASHBOARDS_EDIT_OWN,
                P.SEMANTIC_VIEW,
                P.KB_VIEW,
            }
        ),
    ),
    BuiltinRole(
        "executive",
        "Руководство",
        "Executive",
        "CEO, CDO: итоги экспериментов, портфельный дашборд по всем проектам, чтение базы знаний",
        frozenset({P.EXPERIMENTS_RESULTS, P.DASHBOARDS_VIEW, P.PORTFOLIO_VIEW, P.SEMANTIC_VIEW, P.KB_VIEW}),
    ),
    BuiltinRole(
        "guest",
        "Внешний гость",
        "External guest",
        "Партнёр, издатель: только открытые ему дашборды, доступ ограничен по сроку",
        frozenset({P.DASHBOARDS_VIEW_SHARED}),
    ),
)

BUILTIN_BY_KEY = {r.key: r for r in BUILTIN_ROLES}
