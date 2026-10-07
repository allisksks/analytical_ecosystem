"""Imports demo-content hooks of all modules (registration order; late hooks run last)."""

from app.modules.bi import demo as bi_demo
from app.modules.connectors import demo as connectors_demo
from app.modules.ems import demo as ems_demo
from app.modules.experiments import demo as experiments_demo
from app.modules.kb import demo as kb_demo
from app.modules.semantic import demo as semantic_demo

__all__ = ["bi_demo", "connectors_demo", "ems_demo", "experiments_demo", "kb_demo", "semantic_demo"]
