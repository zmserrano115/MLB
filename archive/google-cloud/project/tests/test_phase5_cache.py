from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
from typing import Any

import pytest
from all_rise.application.operations import OperationsService
from all_rise.cache.circuit import CircuitBreakingRedis
from all_rise.cache.metrics import InMemoryCacheMetrics
from all_rise.cache.versioned import CacheOutcome, VersionedJsonCache, versioned_key
from all_rise.config import ConfigurationError, Settings
from all_rise.repositories.protocols import DataSourceStatusRecord, RepositoryReadiness
from all_rise_api.main import create_app
from all_rise_api.middleware.rate_limit import RedisRateLimiter
from fastapi.testclient import TestClient


class FakeRedis:
    def __init__(self, clock=lambda: 1_000.0) -> None:
        self.clock = clock
        self.values: dict[str, tuple[str, float | None]] = {}
        self.counters: dict[str, tuple[int, float]] = {}
        self.fail = False
        self.operation_calls = 0
        self.lock = threading.Lock()

    def get(self, name: str) -> str | None:
        self.operation_calls += 1
        if self.fail:
            raise ConnectionError("redis unavailable")
        with self.lock:
            item = self.values.get(name)
            if item is None:
                return None
            value, expires_at = item
            if expires_at is not None and expires_at <= self.clock():
                self.values.pop(name, None)
                return None
            return value

    def set(
        self,
        name: str,
        value: str,
        *,
        ex: int | None = None,
        px: int | None = None,
        nx: bool = False,
    ) -> bool:
        self.operation_calls += 1
        if self.fail:
            raise ConnectionError("redis unavailable")
        with self.lock:
            existing = self.values.get(name)
            if existing and existing[1] is not None and existing[1] <= self.clock():
                self.values.pop(name, None)
                existing = None
            if nx and existing is not None:
                return False
            ttl = ex if ex is not None else (px / 1_000 if px is not None else None)
            self.values[name] = (
                value,
                self.clock() + ttl if ttl is not None else None,
            )
            return True

    def eval(self, script: str, numkeys: int, *keys_and_args: str) -> Any:
        self.operation_calls += 1
        del numkeys
        if self.fail:
            raise ConnectionError("redis unavailable")
        key, argument = keys_and_args
        with self.lock:
            if "INCR" in script:
                current, expires_at = self.counters.get(key, (0, self.clock() + int(argument)))
                if expires_at <= self.clock():
                    current, expires_at = 0, self.clock() + int(argument)
                current += 1
                self.counters[key] = (current, expires_at)
                return [current, max(1, int(expires_at - self.clock()))]
            item = self.values.get(key)
            if item and item[0] == argument:
                self.values.pop(key, None)
                return 1
            return 0

    def ping(self) -> bool:
        if self.fail:
            raise ConnectionError("redis unavailable")
        return True

    def close(self) -> None:
        return None


class CountingRepository:
    def __init__(self) -> None:
        self.read_count = 0

    def check_readiness(self) -> RepositoryReadiness:
        return RepositoryReadiness(True, "0002_normalized_shadow_schema")

    def get_data_version(self) -> str:
        return "legacy-sqlite:2026-06-22"

    def get_data_status(self, *, limit: int) -> list[DataSourceStatusRecord]:
        self.read_count += 1
        return [
            DataSourceStatusRecord(
                source="legacy-sqlite",
                watermark="2026-06-22",
                freshness_status="snapshot",
            )
        ][:limit]

    def close(self) -> None:
        return None


def test_versioned_ttl_hit_miss_and_metrics() -> None:
    now = [1_000.0]
    redis = FakeRedis(lambda: now[0])
    metrics = InMemoryCacheMetrics()
    cache = VersionedJsonCache(redis, metrics=metrics, clock=lambda: now[0])
    calls = 0

    def load() -> dict[str, str]:
        nonlocal calls
        calls += 1
        return {"status": "fresh"}

    key = versioned_key("games", ["2026-07-12"], "source-1")
    assert cache.get_or_load(key, load, ttl_seconds=30, negative_ttl_seconds=5).value == {
        "status": "fresh"
    }
    assert (
        cache.get_or_load(key, load, ttl_seconds=30, negative_ttl_seconds=5).outcome
        is CacheOutcome.HIT
    )
    now[0] += 31
    cache.get_or_load(key, load, ttl_seconds=30, negative_ttl_seconds=5)

    assert calls == 2
    assert metrics.snapshot()["hit"] == 1
    assert metrics.snapshot()["miss"] == 2


def test_versions_and_short_negative_ttl() -> None:
    now = [1_000.0]
    redis = FakeRedis(lambda: now[0])
    cache = VersionedJsonCache(redis, clock=lambda: now[0])
    calls = 0

    def missing() -> None:
        nonlocal calls
        calls += 1
        return None

    first = versioned_key("player", [123], "generation-a")
    second = versioned_key("player", [123], "generation-b")
    cache.get_or_load(first, missing, ttl_seconds=60, negative_ttl_seconds=5)
    assert (
        cache.get_or_load(first, missing, ttl_seconds=60, negative_ttl_seconds=5).outcome
        is CacheOutcome.NEGATIVE_HIT
    )
    cache.get_or_load(second, missing, ttl_seconds=60, negative_ttl_seconds=5)
    now[0] += 6
    cache.get_or_load(first, missing, ttl_seconds=60, negative_ttl_seconds=5)
    assert calls == 3


def test_redis_failure_fails_open_to_loader() -> None:
    redis = FakeRedis()
    redis.fail = True
    metrics = InMemoryCacheMetrics()
    cache = VersionedJsonCache(redis, metrics=metrics)

    result = cache.get_or_load(
        "games:today:v1",
        lambda: ["postgres"],
        ttl_seconds=30,
        negative_ttl_seconds=5,
    )

    assert result.value == ["postgres"]
    assert result.outcome is CacheOutcome.DEGRADED
    assert result.stale is True
    assert metrics.snapshot()["degraded_fallback"] >= 1


def test_shared_circuit_breaker_short_circuits_repeated_connection_failures() -> None:
    now = [100.0]
    redis = FakeRedis()
    redis.fail = True
    circuit = CircuitBreakingRedis(redis, reset_seconds=5, clock=lambda: now[0])
    cache = VersionedJsonCache(circuit)

    first = cache.get_or_load(
        "games:today:v1",
        lambda: ["postgres"],
        ttl_seconds=30,
        negative_ttl_seconds=5,
    )
    second = cache.get_or_load(
        "games:today:v1",
        lambda: ["postgres"],
        ttl_seconds=30,
        negative_ttl_seconds=5,
    )

    assert first.outcome is CacheOutcome.DEGRADED
    assert second.outcome is CacheOutcome.DEGRADED
    assert redis.operation_calls == 1

    now[0] += 6
    cache.get_or_load(
        "games:today:v1",
        lambda: ["postgres"],
        ttl_seconds=30,
        negative_ttl_seconds=5,
    )
    assert redis.operation_calls == 2


def test_corrupt_payload_is_replaced_safely() -> None:
    redis = FakeRedis()
    redis.values["games:today:v1"] = ("not-json", None)
    metrics = InMemoryCacheMetrics()
    cache = VersionedJsonCache(redis, metrics=metrics)
    result = cache.get_or_load(
        "games:today:v1",
        lambda: {"safe": True},
        ttl_seconds=30,
        negative_ttl_seconds=5,
    )
    assert result.value == {"safe": True}
    assert metrics.snapshot()["serialization_failure"] == 1


def test_stampede_lease_runs_one_loader() -> None:
    redis = FakeRedis(time.time)
    cache = VersionedJsonCache(
        redis,
        wait_attempts=100,
        wait_interval_seconds=0.005,
    )
    calls = 0
    lock = threading.Lock()

    def slow_load() -> dict[str, bool]:
        nonlocal calls
        with lock:
            calls += 1
        time.sleep(0.05)
        return {"loaded": True}

    def request() -> Any:
        return cache.get_or_load(
            "bvp:1:2:vsource",
            slow_load,
            ttl_seconds=60,
            negative_ttl_seconds=5,
        ).value

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: request(), range(8)))

    assert calls == 1
    assert results == [{"loaded": True}] * 8


def test_two_service_instances_share_cached_result() -> None:
    redis = FakeRedis()
    first_repository = CountingRepository()
    second_repository = CountingRepository()
    first = OperationsService(
        first_repository,
        VersionedJsonCache(redis),
        expected_schema_revision="0002_normalized_shadow_schema",
    )
    second = OperationsService(
        second_repository,
        VersionedJsonCache(redis),
        expected_schema_revision="0002_normalized_shadow_schema",
    )
    assert first.data_status(limit=20) == second.data_status(limit=20)
    assert first_repository.read_count == 1
    assert second_repository.read_count == 0


def test_structurally_invalid_cached_data_falls_back_to_repository() -> None:
    redis = FakeRedis()
    cache = VersionedJsonCache(redis)
    repository = CountingRepository()
    version = sha256(repository.get_data_version().encode()).hexdigest()[:16]
    key = versioned_key("data-status", [20], version)
    assert cache.set(key, [{"unexpected": "shape"}], ttl_seconds=30)
    service = OperationsService(
        repository,
        cache,
        expected_schema_revision="0002_normalized_shadow_schema",
    )

    result = service.data_status_with_cache(limit=20)

    assert result.records[0].source == "legacy-sqlite"
    assert result.cache_outcome == "serialization_error"
    assert result.stale is True
    assert repository.read_count == 1


def test_rate_limit_and_redis_down_fail_open() -> None:
    redis = FakeRedis()
    limiter = RedisRateLimiter(redis, requests=2, window_seconds=60, clock=lambda: 1_000)
    assert limiter.check(key="client", route="/api/v1/data-status").allowed
    assert limiter.check(key="client", route="/api/v1/data-status").allowed
    denied = limiter.check(key="client", route="/api/v1/data-status")
    assert denied.allowed is False
    assert denied.remaining == 0
    assert denied.retry_after_seconds
    redis.fail = True
    degraded = limiter.check(key="client", route="/api/v1/data-status")
    assert degraded.allowed is True
    assert degraded.degraded is True


def test_rate_limit_middleware_returns_safe_429_envelope() -> None:
    settings = Settings(
        app_env="test",
        log_level="WARNING",
        database_url="postgresql+psycopg://test:test@localhost/test",
        redis_url="redis://localhost:6379/15",
        cors_allowed_origins=("https://example.test",),
        build_sha="test",
        schema_revision="0002_normalized_shadow_schema",
        max_body_bytes=1_024,
        slow_request_ms=500,
        db_pool_size=1,
        db_max_overflow=1,
        cache_enabled=False,
        rate_limit_enabled=False,
    )
    application = create_app(settings)

    @application.get("/api/test")
    def api_test() -> dict[str, bool]:
        return {"ok": True}

    limiter = RedisRateLimiter(FakeRedis(), requests=0, window_seconds=60)
    with TestClient(application) as client:
        application.state.rate_limiter = limiter
        response = client.get("/api/test", headers={"x-request-id": "limited_1"})

    assert response.status_code == 429
    assert response.json()["error"] == {
        "code": "rate_limited",
        "message": "Too many requests",
        "request_id": "limited_1",
    }
    assert response.headers["retry-after"]
    assert response.headers["x-request-id"] == "limited_1"


def test_cache_configuration_prefers_dedicated_endpoint_and_validates_booleans(
    monkeypatch,
) -> None:
    monkeypatch.setenv("REDIS_URL", "redis://broker-and-fallback:6379/0")
    monkeypatch.setenv("REDIS_CACHE_URL", "redis://cache-only:6379/0")
    settings = Settings.from_env()
    assert settings.resolved_cache_url == "redis://cache-only:6379/0"

    monkeypatch.setenv("CACHE_ENABLED", "sometimes")
    with pytest.raises(ConfigurationError, match="true or false"):
        Settings.from_env()
