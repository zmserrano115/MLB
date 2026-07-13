from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest
from all_rise.application.operations import OperationsService
from all_rise.cache.versioned import CacheLoadResult, CacheOutcome
from all_rise.config import ConfigurationError, Settings
from all_rise.repositories.protocols import (
    DataSourceStatusRecord,
    RepositoryReadiness,
)
from all_rise.repositories.sqlite import SQLiteOperationsRepository
from all_rise_api.dependencies import get_operations_service
from all_rise_api.main import create_app
from fastapi.testclient import TestClient


class FakeRepository:
    def __init__(
        self,
        readiness: RepositoryReadiness | None = None,
        records: list[DataSourceStatusRecord] | None = None,
        *,
        fail_reads: bool = False,
    ) -> None:
        self.readiness = readiness or RepositoryReadiness(True, "0001_scaffold")
        self.records = records or []
        self.fail_reads = fail_reads

    def check_readiness(self) -> RepositoryReadiness:
        return self.readiness

    def get_data_version(self) -> str:
        return "test-version"

    def get_data_status(self, *, limit: int) -> list[DataSourceStatusRecord]:
        if self.fail_reads:
            raise RuntimeError("private database detail")
        return self.records[:limit]

    def close(self) -> None:
        return None


class FakeCache:
    def __init__(self, *, available: bool = True) -> None:
        self.available = available

    def ping(self) -> bool:
        if not self.available:
            raise ConnectionError("private redis detail")
        return True

    def get_or_load(
        self,
        key: str,
        loader,
        *,
        ttl_seconds: int,
        negative_ttl_seconds: int,
    ) -> CacheLoadResult:
        del key, ttl_seconds, negative_ttl_seconds
        return CacheLoadResult(loader(), CacheOutcome.MISS)

    def close(self) -> None:
        return None


def settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "app_env": "test",
        "log_level": "WARNING",
        "database_url": "postgresql+psycopg://test:test@localhost:5432/test",
        "redis_url": "redis://localhost:6379/15",
        "cors_allowed_origins": ("https://example.test",),
        "build_sha": "abc123",
        "schema_revision": "0001_scaffold",
        "max_body_bytes": 4,
        "slow_request_ms": 500.0,
        "db_pool_size": 1,
        "db_max_overflow": 0,
    }
    values.update(overrides)
    return Settings(**values)  # type: ignore[arg-type]


def client_for(
    repository: FakeRepository | None = None,
    cache: FakeCache | None = None,
    *,
    app_settings: Settings | None = None,
    raise_server_exceptions: bool = True,
) -> TestClient:
    application = create_app(app_settings or settings())
    service = OperationsService(
        repository or FakeRepository(),
        cache or FakeCache(),
        expected_schema_revision="0001_scaffold",
    )
    application.dependency_overrides[get_operations_service] = lambda: service
    return TestClient(application, raise_server_exceptions=raise_server_exceptions)


def test_health_is_dependency_free_and_has_security_headers() -> None:
    with client_for(FakeRepository(fail_reads=True), FakeCache(available=False)) as client:
        response = client.get("/health", headers={"x-request-id": "trace_123"})

    assert response.status_code == 200
    assert response.json() == {
        "data": {"status": "ok", "service": "api"},
        "meta": {
            "request_id": "trace_123",
            "data_version": None,
            "source_time": None,
            "stale": False,
            "pagination": None,
        },
    }
    assert response.headers["x-request-id"] == "trace_123"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"


def test_readiness_allows_degraded_redis_but_rejects_database_failure() -> None:
    with client_for(cache=FakeCache(available=False)) as client:
        degraded = client.get("/ready")
    assert degraded.status_code == 200
    assert degraded.json()["data"]["cache_status"] == "degraded"

    unavailable = FakeRepository(RepositoryReadiness(False, None, "secret detail"))
    with client_for(unavailable) as client:
        failed = client.get("/ready")
    assert failed.status_code == 503
    assert failed.json()["error"]["code"] == "not_ready"
    assert "secret detail" not in failed.text


def test_version_and_bounded_data_status_contracts() -> None:
    record = DataSourceStatusRecord(
        source="mlb-schedule",
        watermark="2026-07-12",
        freshness_status="fresh",
    )
    with client_for(FakeRepository(records=[record])) as client:
        version_response = client.get("/version")
        status_response = client.get("/api/v1/data-status?limit=1")
        invalid_response = client.get("/api/v1/data-status?limit=101")

    assert version_response.json()["data"] == {
        "service": "api",
        "api_version": "0.1.0",
        "build_sha": "abc123",
        "schema_revision": "0001_scaffold",
    }
    assert status_response.status_code == 200
    assert status_response.json()["data"][0]["source"] == "mlb-schedule"
    assert status_response.json()["meta"]["pagination"]["limit"] == 1
    assert invalid_response.status_code == 422
    assert invalid_response.json()["error"]["code"] == "validation_error"


def test_safe_internal_error_and_body_limit() -> None:
    with client_for(FakeRepository(fail_reads=True), raise_server_exceptions=False) as client:
        internal = client.get("/api/v1/data-status")
        oversized = client.request("GET", "/health", content=b"12345")

    assert internal.status_code == 500
    assert internal.json()["error"]["code"] == "internal_error"
    assert "private database detail" not in internal.text
    assert oversized.status_code == 413
    assert oversized.json()["error"]["code"] == "request_too_large"
    assert oversized.headers["x-request-id"]


def test_cors_uses_explicit_allowlist() -> None:
    with client_for() as client:
        allowed = client.options(
            "/health",
            headers={
                "origin": "https://example.test",
                "access-control-request-method": "GET",
            },
        )
        denied = client.options(
            "/health",
            headers={
                "origin": "https://attacker.test",
                "access-control-request-method": "GET",
            },
        )

    assert allowed.headers["access-control-allow-origin"] == "https://example.test"
    assert "access-control-allow-origin" not in denied.headers


def test_production_configuration_rejects_sqlite_and_wildcard_cors() -> None:
    with pytest.raises(ConfigurationError, match="PostgreSQL"):
        settings(app_env="production", database_url="sqlite:///data/mlb.db").validate()
    with pytest.raises(ConfigurationError, match="allowlist"):
        settings(app_env="production", cors_allowed_origins=("*",)).validate()


def test_sqlite_adapter_is_read_only(tmp_path: Path) -> None:
    database_path = tmp_path / "legacy.db"
    with sqlite3.connect(database_path) as connection:
        connection.execute("CREATE TABLE refresh_log (completed_at TEXT)")
        connection.execute("INSERT INTO refresh_log VALUES ('2026-07-12T12:00:00Z')")
        connection.execute("PRAGMA user_version = 7")

    repository = SQLiteOperationsRepository(f"sqlite:///{database_path.as_posix()}")
    readiness = repository.check_readiness()
    rows = repository.get_data_status(limit=1)

    assert readiness == RepositoryReadiness(True, "sqlite-user-version-7")
    assert rows[0].watermark == "2026-07-12T12:00:00Z"
    assert rows[0].detail == "Development-only compatibility adapter"


def test_openapi_snapshot() -> None:
    document = create_app(settings()).openapi()
    actual = {
        "paths": {
            path: {
                "methods": sorted(method for method in operation if method == "get"),
                "responses": sorted(operation["get"]["responses"]),
            }
            for path, operation in document["paths"].items()
        },
        "schemas": sorted(document["components"]["schemas"]),
    }
    fixture_path = Path(__file__).with_name("fixtures") / "openapi_phase3_contract.json"
    expected = json.loads(fixture_path.read_text(encoding="utf-8"))

    assert actual == expected
    limit_schema = document["paths"]["/api/v1/data-status"]["get"]["parameters"][0]["schema"]
    assert limit_schema["minimum"] == 1
    assert limit_schema["maximum"] == 100
