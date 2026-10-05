"""Aggregates module routers under /api/v1."""

from __future__ import annotations

from fastapi import APIRouter

from app.modules.ai.router import router as ai_router
from app.modules.bi.router import router as bi_router
from app.modules.connectors.router import router as connectors_router
from app.modules.ems.router import channels_router
from app.modules.ems.router import router as ems_router
from app.modules.experiments.router import router as experiments_router
from app.modules.iam.router_admin import router as admin_router
from app.modules.iam.router_auth import router as auth_router
from app.modules.kb.router import router as kb_router
from app.modules.query.router import router as query_router
from app.modules.semantic.router import router as semantic_router

api_router = APIRouter()
api_router.include_router(auth_router)
api_router.include_router(admin_router)
api_router.include_router(connectors_router)
api_router.include_router(query_router)
api_router.include_router(semantic_router)
api_router.include_router(bi_router)
api_router.include_router(kb_router)
api_router.include_router(ems_router)
api_router.include_router(channels_router)
api_router.include_router(experiments_router)
api_router.include_router(ai_router)
