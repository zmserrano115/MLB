"""Read-only repository contracts shared by API and worker delivery layers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class RepositoryReadiness:
    reachable: bool
    schema_revision: str | None
    detail: str | None = None


@dataclass(frozen=True, slots=True)
class DataSourceStatusRecord:
    source: str
    watermark: str | None
    freshness_status: str
    last_success_at: str | None = None
    last_failure_at: str | None = None
    detail: str | None = None


class OperationsRepository(Protocol):
    """Bounded operational reads; implementations must never mutate data."""

    def check_readiness(self) -> RepositoryReadiness: ...

    def get_data_status(self, *, limit: int) -> list[DataSourceStatusRecord]: ...

    def close(self) -> None: ...
