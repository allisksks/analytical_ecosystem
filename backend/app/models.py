"""Imports every ORM model so Alembic autogenerate and create_all see the full metadata."""

from __future__ import annotations

import importlib

MODEL_MODULES: list[str] = [
    "app.modules.iam.models",
    "app.modules.audit.models",
    "app.modules.connectors.models",
    "app.modules.query.models",
    "app.modules.semantic.models",
    "app.modules.bi.models",
]


def load_all_models() -> None:
    for module in MODEL_MODULES:
        importlib.import_module(module)
