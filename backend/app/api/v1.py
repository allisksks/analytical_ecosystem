"""Aggregates module routers under /api/v1."""

from __future__ import annotations

from fastapi import APIRouter

from app.modules.iam.router_admin import router as admin_router
from app.modules.iam.router_auth import router as auth_router

api_router = APIRouter()
api_router.include_router(auth_router)
api_router.include_router(admin_router)
