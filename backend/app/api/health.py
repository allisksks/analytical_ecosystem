"""Liveness / readiness probes for Docker and Kubernetes."""

from __future__ import annotations

from fastapi import APIRouter, Response, status
from sqlalchemy import text

from app import __version__
from app.core.db import get_engine

router = APIRouter(tags=["health"])


@router.get("/healthz", summary="Liveness probe")
async def healthz() -> dict[str, str]:
    return {"status": "ok", "version": __version__}


@router.get("/readyz", summary="Readiness probe (checks metadata DB)")
async def readyz(response: Response) -> dict[str, str]:
    try:
        async with get_engine().connect() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception as exc:  # pragma: no cover - depends on infra
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {"status": "unavailable", "reason": type(exc).__name__}
    return {"status": "ready"}
