"""Domain errors and their mapping to HTTP responses (RFC 7807 problem+json)."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse


class AppError(Exception):
    status_code = 400
    code = "bad_request"

    def __init__(self, message: str, *, details: Any = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details


class NotFoundError(AppError):
    status_code = 404
    code = "not_found"


class ConflictError(AppError):
    status_code = 409
    code = "conflict"


class ValidationFailed(AppError):
    status_code = 422
    code = "validation_failed"


class AuthError(AppError):
    status_code = 401
    code = "unauthorized"


class PermissionDenied(AppError):
    status_code = 403
    code = "forbidden"


class UpstreamError(AppError):
    status_code = 502
    code = "upstream_error"


class FeatureDisabled(AppError):
    status_code = 503
    code = "feature_disabled"


def _problem(status: int, code: str, message: str, details: Any = None) -> JSONResponse:
    body: dict[str, Any] = {"type": code, "title": message, "status": status}
    if details is not None:
        body["details"] = details
    headers = {"WWW-Authenticate": "Bearer"} if status == 401 else None
    return JSONResponse(body, status_code=status, media_type="application/problem+json", headers=headers)


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(_: Request, exc: AppError) -> JSONResponse:
        return _problem(exc.status_code, exc.code, exc.message, exc.details)
