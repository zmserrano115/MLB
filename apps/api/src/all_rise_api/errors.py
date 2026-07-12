from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


class ApiError(Exception):
    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        *,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details


def request_id_for(request: Request) -> str:
    return str(getattr(request.state, "request_id", "unavailable"))


def error_payload(
    *,
    code: str,
    message: str,
    request_id: str,
    details: dict[str, Any] | None = None,
) -> dict[str, object]:
    error: dict[str, object] = {
        "code": code,
        "message": message,
        "request_id": request_id,
    }
    if details is not None:
        error["details"] = details
    return {"error": error}


def install_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def handle_api_error(request: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=error_payload(
                code=exc.code,
                message=exc.message,
                request_id=request_id_for(request),
                details=exc.details,
            ),
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        safe_errors = [
            {"location": list(error["loc"]), "message": error["msg"]} for error in exc.errors()
        ]
        return JSONResponse(
            status_code=422,
            content=error_payload(
                code="validation_error",
                message="Request validation failed",
                request_id=request_id_for(request),
                details={"errors": safe_errors},
            ),
        )

    @app.exception_handler(Exception)
    async def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
        del exc
        return JSONResponse(
            status_code=500,
            content=error_payload(
                code="internal_error",
                message="The request could not be completed",
                request_id=request_id_for(request),
            ),
        )
