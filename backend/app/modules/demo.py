"""Imports demo-content hooks of all modules (order matters: sources before metrics/dashboards)."""

from app.modules.connectors import demo as connectors_demo

__all__ = ["connectors_demo"]
