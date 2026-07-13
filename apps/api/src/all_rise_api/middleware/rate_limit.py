from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass
from typing import Any, Protocol

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp

from all_rise_api.errors import error_payload


@dataclass(frozen=True, slots=True)
class RateLimitDecision:
    allowed: bool
    remaining: int | None = None
    retry_after_seconds: int | None = None
    degraded: bool = False


class RateLimiter(Protocol):
    def check(self, *, key: str, route: str) -> RateLimitDecision: ...

    def close(self) -> None: ...


class AllowAllRateLimiter:
    def check(self, *, key: str, route: str) -> RateLimitDecision:
        del key, route
        return RateLimitDecision(allowed=True)

    def close(self) -> None:
        return None


class RedisRateLimiter:
    SCRIPT = """
        local current = redis.call('INCR', KEYS[1])
        if current == 1 then
            redis.call('EXPIRE', KEYS[1], ARGV[1])
        end
        local ttl = redis.call('TTL', KEYS[1])
        return {current, ttl}
    """

    def __init__(
        self,
        client: Any,
        *,
        requests: int,
        window_seconds: int,
        clock: Any = time.time,
    ) -> None:
        self._client = client
        self._requests = requests
        self._window_seconds = window_seconds
        self._clock = clock

    def check(self, *, key: str, route: str) -> RateLimitDecision:
        bucket = int(self._clock()) // self._window_seconds
        identity = hashlib.sha256(key.encode("utf-8")).hexdigest()[:24]
        route_key = hashlib.sha256(route.encode("utf-8")).hexdigest()[:16]
        redis_key = f"rate-limit:{identity}:{route_key}:{bucket}"
        try:
            current, ttl = self._client.eval(self.SCRIPT, 1, redis_key, str(self._window_seconds))
            count = int(current)
            retry_after = max(1, int(ttl))
            return RateLimitDecision(
                allowed=count <= self._requests,
                remaining=max(0, self._requests - count),
                retry_after_seconds=retry_after if count > self._requests else None,
            )
        except Exception:
            return RateLimitDecision(allowed=True, degraded=True)

    def close(self) -> None:
        self._client.close()


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if not request.url.path.startswith("/api/"):
            return await call_next(request)
        limiter = getattr(request.app.state, "rate_limiter", AllowAllRateLimiter())
        client_key = request.client.host if request.client else "unknown"
        decision = limiter.check(key=client_key, route=request.url.path)
        if decision.allowed:
            response = await call_next(request)
            if decision.remaining is not None:
                response.headers["x-rate-limit-remaining"] = str(decision.remaining)
            if decision.degraded:
                response.headers["x-rate-limit-status"] = "degraded"
            return response
        request_id = str(getattr(request.state, "request_id", "unavailable"))
        response = JSONResponse(
            status_code=429,
            content=error_payload(
                code="rate_limited",
                message="Too many requests",
                request_id=request_id,
            ),
        )
        response.headers["retry-after"] = str(decision.retry_after_seconds or 1)
        response.headers["x-rate-limit-remaining"] = "0"
        return response
