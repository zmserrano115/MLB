from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any, Protocol


class ClaimState(StrEnum):
    ACQUIRED = "acquired"
    DUPLICATE = "duplicate"
    IN_PROGRESS = "in_progress"
    DEAD_LETTER = "dead_letter"


class ExecutionState(StrEnum):
    SUCCEEDED = "succeeded"
    DUPLICATE = "duplicate"
    IN_PROGRESS = "in_progress"
    RETRY = "retry"
    DEAD_LETTER = "dead_letter"


@dataclass(frozen=True, slots=True)
class TaskRequest:
    task_name: str
    idempotency_key: str
    source: str
    scope: str
    payload: dict[str, Any] = field(default_factory=dict)
    max_attempts: int = 5

    def __post_init__(self) -> None:
        limits = {
            "task_name": (self.task_name, 96),
            "idempotency_key": (self.idempotency_key, 128),
            "source": (self.source, 64),
            "scope": (self.scope, 160),
        }
        for name, (value, maximum) in limits.items():
            if not value or len(value) > maximum:
                raise ValueError(f"{name} must contain 1-{maximum} characters")
        if self.max_attempts <= 0:
            raise ValueError("max_attempts must be positive")


@dataclass(frozen=True, slots=True)
class ClaimResult:
    state: ClaimState
    run_id: int
    attempt: int


@dataclass(frozen=True, slots=True)
class Publication:
    source: str
    scope: str
    watermark: str
    source_version: str
    detail: str | None = None
    dataset: str | None = None
    records: tuple[dict[str, Any], ...] = ()


@dataclass(frozen=True, slots=True)
class TaskResult:
    payload: dict[str, Any] = field(default_factory=dict)
    processed_items: int = 0
    failed_items: int = 0
    max_failed_items: int = 0
    facts_loaded: int = 0
    publication: Publication | None = None


@dataclass(frozen=True, slots=True)
class ExecutionResult:
    state: ExecutionState
    run_id: int
    attempt: int
    retry_delay_ms: int | None = None
    message: str | None = None


@dataclass(frozen=True, slots=True)
class ArtifactRecord:
    source: str
    generation: str
    uri: str
    sha256: str
    size_bytes: int
    fetched_at: datetime
    source_version: str | None
    inventory: dict[str, Any]


class JobStore(Protocol):
    def claim(
        self, request: TaskRequest, *, now: datetime, stale_after_seconds: int
    ) -> ClaimResult: ...

    def heartbeat(self, run_id: int, attempt: int, *, now: datetime) -> bool: ...

    def record_item(
        self,
        run_id: int,
        attempt: int,
        *,
        item_key: str,
        status: str,
        payload: dict[str, Any],
        error_code: str | None,
        message: str | None,
        now: datetime,
    ) -> None: ...

    def register_artifact(self, artifact: ArtifactRecord) -> None: ...

    def succeed(
        self,
        run_id: int,
        attempt: int,
        result: TaskResult,
        *,
        now: datetime,
    ) -> None: ...

    def fail(
        self,
        run_id: int,
        attempt: int,
        *,
        error_code: str,
        message: str,
        retryable: bool,
        next_retry_at: datetime | None,
        now: datetime,
    ) -> bool: ...

    def recover_stale(self, *, now: datetime, stale_after_seconds: int) -> int: ...

    def close(self) -> None: ...
