"""Operational use cases shared by HTTP and worker delivery layers."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
from typing import Any, Protocol

from all_rise.cache.versioned import CacheLoadResult, PassThroughCache, versioned_key
from all_rise.config import Settings
from all_rise.repositories.postgres import PostgresOperationsRepository
from all_rise.repositories.protocols import ApplicationRepository, DataSourceStatusRecord, OperationsRepository
from all_rise.repositories.sqlite import SQLiteOperationsRepository


class CacheProbe(Protocol):
    def ping(self) -> bool: ...

    def get_or_load(
        self,
        key: str,
        loader: Any,
        *,
        ttl_seconds: int,
        negative_ttl_seconds: int,
    ) -> CacheLoadResult: ...

    def close(self) -> None: ...


@dataclass(frozen=True, slots=True)
class OperationsReadiness:
    ready: bool
    database_status: str
    cache_status: str
    schema_revision: str | None
    detail: str | None = None


@dataclass(frozen=True, slots=True)
class DataStatusResult:
    records: list[DataSourceStatusRecord]
    cache_outcome: str
    stale: bool


class OperationsService:
    def __init__(
        self,
        repository: OperationsRepository,
        cache_probe: CacheProbe,
        *,
        expected_schema_revision: str,
        cache_ttl_seconds: int = 30,
        negative_ttl_seconds: int = 5,
    ) -> None:
        self._repository = repository
        self._cache_probe = cache_probe
        self._expected_schema_revision = expected_schema_revision
        self._cache_ttl_seconds = cache_ttl_seconds
        self._negative_ttl_seconds = negative_ttl_seconds

    def readiness(self) -> OperationsReadiness:
        database = self._repository.check_readiness()
        if not database.reachable:
            return OperationsReadiness(
                False,
                "unavailable",
                "unknown",
                database.schema_revision,
                database.detail,
            )
        schema_matches = database.schema_revision == self._expected_schema_revision
        try:
            cache_ready = self._cache_probe.ping()
        except Exception:
            cache_ready = False
        return OperationsReadiness(
            schema_matches,
            "ready" if schema_matches else "schema-mismatch",
            "ready" if cache_ready else "degraded",
            database.schema_revision,
            None if schema_matches else "Database schema is not at the expected revision",
        )

    def data_status(self, *, limit: int) -> list[DataSourceStatusRecord]:
        return self.data_status_with_cache(limit=limit).records

    def data_status_with_cache(self, *, limit: int) -> DataStatusResult:
        source_version = self._repository.get_data_version()
        version = sha256(source_version.encode("utf-8")).hexdigest()[:16]
        key = versioned_key("data-status", [limit], version)

        def load() -> list[dict[str, str | None]]:
            return [asdict(record) for record in self._repository.get_data_status(limit=limit)]

        result = self._cache_probe.get_or_load(
            key,
            load,
            ttl_seconds=self._cache_ttl_seconds,
            negative_ttl_seconds=self._negative_ttl_seconds,
        )
        if not isinstance(result.value, list):
            return DataStatusResult(
                self._repository.get_data_status(limit=limit),
                "degraded",
                True,
            )
        try:
            records = [DataSourceStatusRecord(**record) for record in result.value]
        except (TypeError, KeyError):
            return DataStatusResult(
                self._repository.get_data_status(limit=limit),
                "serialization_error",
                True,
            )
        return DataStatusResult(records, result.outcome.value, result.stale)

    def close(self) -> None:
        self._cache_probe.close()
        self._repository.close()


def build_operations_repository(settings: Settings) -> ApplicationRepository:
    if settings.database_scheme == "sqlite":
        if settings.is_production:
            raise ValueError("SQLite cannot be used in production")
        return SQLiteOperationsRepository(settings.database_url)
    if not settings.database_scheme.startswith("postgresql"):
        raise ValueError("Unsupported database scheme")
    return PostgresOperationsRepository(
        settings.database_url,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
    )


def build_pass_through_cache() -> PassThroughCache:
    return PassThroughCache()
