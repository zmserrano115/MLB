from __future__ import annotations

import json
import logging
import re
import time
from uuid import uuid4

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp

from all_rise_api.errors import error_payload

REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
logger = logging.getLogger("all_rise_api.requests")


def add_security_headers(response: Response, request_id: str) -> None:
    response.headers["x-request-id"] = request_id
    response.headers["x-content-type-options"] = "nosniff"
    response.headers["x-frame-options"] = "DENY"
    response.headers["referrer-policy"] = "no-referrer"
    response.headers["permissions-policy"] = "camera=(), microphone=(), geolocation=()"


class RequestContextMiddleware(BaseHTTPMiddleware):
    def __init__(
        self,
        app: ASGIApp,
        *,
        max_body_bytes: int,
        slow_request_ms: float,
    ) -> None:
        super().__init__(app)
        self._max_body_bytes = max_body_bytes
        self._slow_request_ms = slow_request_ms

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        supplied_request_id = request.headers.get("x-request-id", "")
        request_id = (
            supplied_request_id
            if REQUEST_ID_PATTERN.fullmatch(supplied_request_id)
            else str(uuid4())
        )
        request.state.request_id = request_id
        content_length = request.headers.get("content-length")
        if content_length:
            try:
                body_size = int(content_length)
            except ValueError:
                body_size = self._max_body_bytes + 1
            if body_size > self._max_body_bytes:
                oversized_response = JSONResponse(
                    status_code=413,
                    content=error_payload(
                        code="request_too_large",
                        message="Request body exceeds the configured limit",
                        request_id=request_id,
                    ),
                )
                add_security_headers(oversized_response, request_id)
                return oversized_response

        started = time.perf_counter()
        response = await call_next(request)
        duration_ms = (time.perf_counter() - started) * 1000.0
        add_security_headers(response, request_id)
        log_record = {
            "event": "http_request",
            "request_id": request_id,
            "method": request.method,
            "route": request.url.path,
            "status": response.status_code,
            "duration_ms": round(duration_ms, 2),
            "slow": duration_ms >= self._slow_request_ms,
        }
        logger.info(json.dumps(log_record, separators=(",", ":")))
        return response
