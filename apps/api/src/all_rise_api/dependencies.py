from __future__ import annotations

from typing import cast

from all_rise.application.operations import (
    OperationsService,
    build_operations_repository,
)
from all_rise.application.slate import SlateService
from all_rise.cache.circuit import CircuitBreakingRedis
from all_rise.cache.metrics import InMemoryCacheMetrics
from all_rise.cache.versioned import PassThroughCache, VersionedJsonCache
from all_rise.config import Settings
from fastapi import Request
from redis import Redis
from redis.backoff import NoBackoff
from redis.retry import Retry

from all_rise_api.middleware.rate_limit import AllowAllRateLimiter, RedisRateLimiter


def create_shared_cache(
    settings: Settings,
    client: CircuitBreakingRedis | None = None,
) -> tuple[VersionedJsonCache | PassThroughCache, InMemoryCacheMetrics]:
    metrics = InMemoryCacheMetrics()
    if not settings.cache_enabled:
        return PassThroughCache(), metrics
    client = client or create_redis_client(settings)
    return (
        VersionedJsonCache(
            client,
            metrics=metrics,
            lease_ttl_ms=settings.cache_lease_ttl_ms,
        ),
        metrics,
    )


def create_operations_service(
    settings: Settings,
    client: CircuitBreakingRedis | None = None,
) -> tuple[OperationsService, InMemoryCacheMetrics]:
    cache, metrics = create_shared_cache(settings, client)
    service = OperationsService(
        build_operations_repository(settings),
        cache,
        expected_schema_revision=settings.schema_revision,
        cache_ttl_seconds=settings.cache_default_ttl_seconds,
        negative_ttl_seconds=settings.cache_negative_ttl_seconds,
    )
    return service, metrics


def create_application_services(
    settings: Settings,
    client: CircuitBreakingRedis | None = None,
) -> tuple[OperationsService, SlateService, InMemoryCacheMetrics]:
    cache, metrics = create_shared_cache(settings, client)
    repository = build_operations_repository(settings)
    operations = OperationsService(
        repository,
        cache,
        expected_schema_revision=settings.schema_revision,
        cache_ttl_seconds=settings.cache_default_ttl_seconds,
        negative_ttl_seconds=settings.cache_negative_ttl_seconds,
    )
    slate = SlateService(
        repository,
        cache,
        cache_ttl_seconds=settings.cache_default_ttl_seconds,
        negative_ttl_seconds=settings.cache_negative_ttl_seconds,
    )
    return operations, slate, metrics


def create_rate_limiter(
    settings: Settings,
    client: CircuitBreakingRedis | None = None,
) -> RedisRateLimiter | AllowAllRateLimiter:
    if not settings.rate_limit_enabled:
        return AllowAllRateLimiter()
    client = client or create_redis_client(settings)
    return RedisRateLimiter(
        client,
        requests=settings.rate_limit_requests,
        window_seconds=settings.rate_limit_window_seconds,
    )


def create_redis_client(settings: Settings) -> CircuitBreakingRedis:
    timeout_seconds = settings.redis_timeout_ms / 1_000
    client: Redis = Redis.from_url(
        settings.resolved_cache_url,
        socket_connect_timeout=timeout_seconds,
        socket_timeout=timeout_seconds,
        decode_responses=True,
        retry=Retry(NoBackoff(), 0),
    )
    return CircuitBreakingRedis(client)


def get_operations_service(request: Request) -> OperationsService:
    return cast(OperationsService, request.app.state.operations_service)


def get_slate_service(request: Request) -> SlateService:
    return cast(SlateService, request.app.state.slate_service)


def get_settings(request: Request) -> Settings:
    return cast(Settings, request.app.state.settings)
