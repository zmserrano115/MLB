from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from all_rise.config import Settings
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from all_rise_api.api.v1.routes.operations import api_version, router
from all_rise_api.dependencies import (
    create_operations_service,
    create_rate_limiter,
    create_redis_client,
)
from all_rise_api.errors import install_exception_handlers
from all_rise_api.middleware.rate_limit import RateLimitMiddleware
from all_rise_api.middleware.request_context import RequestContextMiddleware


def configure_logging(settings: Settings) -> None:
    logging.basicConfig(
        level=getattr(logging, settings.log_level, logging.INFO),
        format="%(message)s",
    )


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved_settings = settings or Settings.from_env()
    configure_logging(resolved_settings)

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        redis_client = (
            create_redis_client(resolved_settings)
            if resolved_settings.cache_enabled or resolved_settings.rate_limit_enabled
            else None
        )
        service, cache_metrics = create_operations_service(resolved_settings, redis_client)
        rate_limiter = create_rate_limiter(resolved_settings, redis_client)
        application.state.operations_service = service
        application.state.cache_metrics = cache_metrics
        application.state.rate_limiter = rate_limiter
        try:
            yield
        finally:
            rate_limiter.close()
            service.close()

    application = FastAPI(
        title="All Rise Analytics API",
        version=api_version(),
        lifespan=lifespan,
    )
    application.state.settings = resolved_settings
    application.add_middleware(
        CORSMiddleware,
        allow_origins=list(resolved_settings.cors_allowed_origins),
        allow_credentials=False,
        allow_methods=["GET", "OPTIONS"],
        allow_headers=["accept", "content-type", "if-none-match", "x-request-id"],
        expose_headers=["etag", "x-cache-status", "x-request-id", "x-rate-limit-remaining"],
    )
    application.add_middleware(
        RateLimitMiddleware,
    )
    application.add_middleware(
        RequestContextMiddleware,
        max_body_bytes=resolved_settings.max_body_bytes,
        slow_request_ms=resolved_settings.slow_request_ms,
    )
    install_exception_handlers(application)
    application.include_router(router)
    return application


settings = Settings.from_env()
app = create_app(settings)
