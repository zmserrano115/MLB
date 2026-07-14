from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from typing import Any

from all_rise.jobs.artifacts import ArtifactStore, StoredArtifact
from all_rise.jobs.contracts import (
    ArtifactRecord,
    ClaimState,
    ExecutionResult,
    ExecutionState,
    JobStore,
    TaskRequest,
    TaskResult,
)


class RetryableTaskError(RuntimeError):
    """A provider or infrastructure failure that is safe to retry."""


class QualityGateError(RuntimeError):
    """A generation failed validation and must never be published."""


TaskHandler = Callable[[dict[str, Any], "TaskContext"], TaskResult]


class TaskRegistry:
    def __init__(self) -> None:
        self._handlers: dict[str, TaskHandler] = {}

    def register(self, name: str, handler: TaskHandler) -> None:
        if not name or name in self._handlers:
            raise ValueError(f"task handler already registered: {name}")
        self._handlers[name] = handler

    def get(self, name: str) -> TaskHandler:
        try:
            return self._handlers[name]
        except KeyError as exc:
            raise ValueError(f"unknown task: {name}") from exc

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._handlers))


@dataclass(slots=True)
class TaskContext:
    store: JobStore
    artifact_store: ArtifactStore
    run_id: int
    attempt: int
    clock: Callable[[], datetime]

    def heartbeat(self) -> None:
        if not self.store.heartbeat(self.run_id, self.attempt, now=self.clock()):
            raise RuntimeError("task execution lease was lost")

    def record_item(
        self,
        item_key: str,
        *,
        status: str,
        payload: dict[str, Any] | None = None,
        error_code: str | None = None,
        message: str | None = None,
    ) -> None:
        self.store.record_item(
            self.run_id,
            self.attempt,
            item_key=item_key,
            status=status,
            payload=payload or {},
            error_code=error_code,
            message=message,
            now=self.clock(),
        )

    def put_artifact(
        self,
        *,
        source: str,
        generation: str,
        name: str,
        data: bytes,
        source_version: str | None = None,
        inventory: dict[str, Any] | None = None,
        content_type: str = "application/octet-stream",
    ) -> StoredArtifact:
        stored = self.artifact_store.put_bytes(
            source=source,
            generation=generation,
            name=name,
            data=data,
            content_type=content_type,
        )
        self.store.register_artifact(
            ArtifactRecord(
                source=source,
                generation=generation,
                uri=stored.uri,
                sha256=stored.sha256,
                size_bytes=stored.size_bytes,
                fetched_at=self.clock(),
                source_version=source_version,
                inventory=inventory or {},
            )
        )
        return stored


class JobExecutor:
    def __init__(
        self,
        store: JobStore,
        artifact_store: ArtifactStore,
        registry: TaskRegistry,
        *,
        stale_after_seconds: int = 300,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._store = store
        self._artifacts = artifact_store
        self._registry = registry
        self._stale_after_seconds = stale_after_seconds
        self._clock = clock

    def execute(self, request: TaskRequest) -> ExecutionResult:
        handler = self._registry.get(request.task_name)
        now = self._clock()
        claim = self._store.claim(
            request,
            now=now,
            stale_after_seconds=self._stale_after_seconds,
        )
        passive_states = {
            ClaimState.DUPLICATE: ExecutionState.DUPLICATE,
            ClaimState.IN_PROGRESS: ExecutionState.IN_PROGRESS,
            ClaimState.DEAD_LETTER: ExecutionState.DEAD_LETTER,
        }
        if claim.state is not ClaimState.ACQUIRED:
            return ExecutionResult(passive_states[claim.state], claim.run_id, claim.attempt)

        context = TaskContext(
            self._store,
            self._artifacts,
            claim.run_id,
            claim.attempt,
            self._clock,
        )
        try:
            result = handler(request.payload, context)
            if result.failed_items > result.max_failed_items:
                raise QualityGateError(
                    f"{result.failed_items} failed items exceeds threshold "
                    f"{result.max_failed_items}"
                )
            self._store.succeed(claim.run_id, claim.attempt, result, now=self._clock())
            return ExecutionResult(
                ExecutionState.SUCCEEDED,
                claim.run_id,
                claim.attempt,
                result_payload=result.payload,
            )
        except Exception as exc:
            retryable = isinstance(exc, RetryableTaskError)
            delay_ms = retry_delay_ms(request.idempotency_key, claim.attempt)
            next_retry = self._clock() + timedelta(milliseconds=delay_ms) if retryable else None
            can_retry = self._store.fail(
                claim.run_id,
                claim.attempt,
                error_code=type(exc).__name__,
                message=str(exc) or type(exc).__name__,
                retryable=retryable,
                next_retry_at=next_retry,
                now=self._clock(),
            )
            return ExecutionResult(
                ExecutionState.RETRY if can_retry else ExecutionState.DEAD_LETTER,
                claim.run_id,
                claim.attempt,
                retry_delay_ms=delay_ms if can_retry else None,
                message=str(exc) or type(exc).__name__,
            )

    def recover_stale(self) -> int:
        return self._store.recover_stale(
            now=self._clock(), stale_after_seconds=self._stale_after_seconds
        )


def retry_delay_ms(idempotency_key: str, attempt: int) -> int:
    """Bounded exponential backoff with stable per-task jitter (15s to 15m)."""
    base = min(900_000, 15_000 * (2 ** max(0, attempt - 1)))
    digest = sha256(f"{idempotency_key}:{attempt}".encode()).digest()
    jitter = 0.75 + (int.from_bytes(digest[:2]) / 65_535) * 0.5
    return max(1_000, int(base * jitter))
