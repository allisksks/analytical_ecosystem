"""Imports demo-content hooks of all modules (order matters: sources before metrics/dashboards)."""

from app.modules.bi import demo as bi_demo
from app.modules.connectors import demo as connectors_demo
from app.modules.semantic import demo as semantic_demo

__all__ = ["bi_demo", "connectors_demo", "semantic_demo"]
