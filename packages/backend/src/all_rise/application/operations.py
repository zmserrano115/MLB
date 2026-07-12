"""Operational use cases shared by HTTP and worker delivery layers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from all_rise.config import Settings
from all_rise.repositories.postgres import PostgresOperationsRepository
from all_rise.repositories.protocols import DataSourceStatusRecord, OperationsRepository
from all_rise.repositories.sqlite import SQLiteOperationsRepository


class CacheProbe(Protocol):
    def ping(self) -> bool: ...

    def close(self) -> None: ...


@dataclass(frozen=True, slots=True)
class OperationsReadiness:
    ready: bool
    database_status: str
    cache_status: str
    schema_revision: str | None
    detail: str | None = None


class OperationsService:
    def __init__(
        self,
        repository: OperationsRepository,
        cache_probe: CacheProbe,
        *,
        expected_schema_revision: str,
    ) -> None:
        self._repository = repository
        self._cache_probe = cache_probe
        self._expected_schema_revision = expected_schema_revision

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
        return self._repository.get_data_status(limit=limit)

    def close(self) -> None:
        self._cache_probe.close()
        self._repository.close()


def build_operations_repository(settings: Settings) -> OperationsRepository:
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
