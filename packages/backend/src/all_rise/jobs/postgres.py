from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import create_engine, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from all_rise.jobs.contracts import (
    ArtifactRecord,
    ClaimResult,
    ClaimState,
    TaskRequest,
    TaskResult,
)
from all_rise.models import (
    DataSourceStatus,
    ProcessingCheckpoint,
    RefreshRun,
    RefreshRunItem,
    SourceArtifact,
)


class PostgresJobStore:
    """Transactional PostgreSQL authority for task execution and publication."""

    def __init__(
        self,
        database_url: str,
        *,
        pool_size: int = 2,
        max_overflow: int = 2,
    ) -> None:
        self._engine: Engine = create_engine(
            database_url,
            pool_pre_ping=True,
            pool_size=pool_size,
            max_overflow=max_overflow,
        )
        self._sessions = sessionmaker(self._engine, expire_on_commit=False)

    def claim(
        self,
        request: TaskRequest,
        *,
        now: datetime,
        stale_after_seconds: int,
    ) -> ClaimResult:
        values = {
            "idempotency_key": request.idempotency_key,
            "task_name": request.task_name,
            "source": request.source,
            "scope": request.scope,
            "status": "running",
            "attempt": 1,
            "max_attempts": request.max_attempts,
            "games_checked": 0,
            "games_processed": 0,
            "facts_loaded": 0,
            "input_payload": request.payload,
            "created_at": now,
            "started_at": now,
            "heartbeat_at": now,
        }
        with self._sessions.begin() as session:
            created_id = session.execute(
                insert(RefreshRun)
                .values(**values)
                .on_conflict_do_nothing(index_elements=[RefreshRun.idempotency_key])
                .returning(RefreshRun.id)
            ).scalar_one_or_none()
            if created_id is not None:
                return ClaimResult(ClaimState.ACQUIRED, int(created_id), 1)

            run = session.execute(
                select(RefreshRun)
                .where(RefreshRun.idempotency_key == request.idempotency_key)
                .with_for_update()
            ).scalar_one()
            if run.task_name != request.task_name or run.input_payload != request.payload:
                raise ValueError("idempotency key was reused for a different task or payload")
            if run.status == "succeeded":
                return ClaimResult(ClaimState.DUPLICATE, run.id, run.attempt)
            fresh_cutoff = now - timedelta(seconds=stale_after_seconds)
            if run.status == "running" and run.heartbeat_at and run.heartbeat_at >= fresh_cutoff:
                return ClaimResult(ClaimState.IN_PROGRESS, run.id, run.attempt)
            if run.next_retry_at and run.next_retry_at > now:
                return ClaimResult(ClaimState.IN_PROGRESS, run.id, run.attempt)
            if run.attempt >= run.max_attempts or run.status == "dead_letter":
                run.status = "dead_letter"
                run.dead_lettered_at = run.dead_lettered_at or now
                return ClaimResult(ClaimState.DEAD_LETTER, run.id, run.attempt)

            run.status = "running"
            run.attempt += 1
            run.started_at = now
            run.heartbeat_at = now
            run.next_retry_at = None
            run.completed_at = None
            run.error_code = None
            run.message = None
            return ClaimResult(ClaimState.ACQUIRED, run.id, run.attempt)

    def heartbeat(self, run_id: int, attempt: int, *, now: datetime) -> bool:
        with self._sessions.begin() as session:
            run = session.get(RefreshRun, run_id, with_for_update=True)
            if run is None or run.status != "running" or run.attempt != attempt:
                return False
            run.heartbeat_at = now
            return True

    def record_item(
        self,
        run_id: int,
        attempt: int,
        *,
        item_key: str,
        status: str,
        payload: dict[str, object],
        error_code: str | None,
        message: str | None,
        now: datetime,
    ) -> None:
        completed_at = now if status in {"succeeded", "failed", "skipped"} else None
        statement = insert(RefreshRunItem).values(
            run_id=run_id,
            item_key=item_key,
            status=status,
            attempt=attempt,
            error_code=error_code,
            message=message,
            payload=payload,
            created_at=now,
            completed_at=completed_at,
        )
        with self._sessions.begin() as session:
            session.execute(
                statement.on_conflict_do_update(
                    index_elements=[
                        RefreshRunItem.run_id,
                        RefreshRunItem.item_key,
                        RefreshRunItem.attempt,
                    ],
                    set_={
                        "status": status,
                        "error_code": error_code,
                        "message": message,
                        "payload": payload,
                        "completed_at": completed_at,
                    },
                )
            )

    def register_artifact(self, artifact: ArtifactRecord) -> None:
        statement = (
            insert(SourceArtifact)
            .values(
                source=artifact.source,
                generation=artifact.generation,
                uri=artifact.uri,
                sha256=artifact.sha256,
                size_bytes=artifact.size_bytes,
                fetched_at=artifact.fetched_at,
                source_version=artifact.source_version,
                inventory=artifact.inventory,
            )
            .on_conflict_do_nothing(
                index_elements=[
                    SourceArtifact.source,
                    SourceArtifact.generation,
                    SourceArtifact.sha256,
                ]
            )
        )
        with self._sessions.begin() as session:
            session.execute(statement)

    def succeed(
        self,
        run_id: int,
        attempt: int,
        result: TaskResult,
        *,
        now: datetime,
    ) -> None:
        with self._sessions.begin() as session:
            run = self._owned_run(session, run_id, attempt)
            run.status = "succeeded"
            run.games_processed = result.processed_items
            run.facts_loaded = result.facts_loaded
            run.result_payload = result.payload
            run.completed_at = now
            run.heartbeat_at = now
            if result.publication is not None:
                publication = result.publication
                checkpoint = insert(ProcessingCheckpoint).values(
                    source=publication.source,
                    scope=publication.scope,
                    watermark=publication.watermark,
                    source_version=publication.source_version,
                    updated_at=now,
                )
                session.execute(
                    checkpoint.on_conflict_do_update(
                        index_elements=[
                            ProcessingCheckpoint.source,
                            ProcessingCheckpoint.scope,
                        ],
                        set_={
                            "watermark": publication.watermark,
                            "source_version": publication.source_version,
                            "updated_at": now,
                        },
                    )
                )
                status = insert(DataSourceStatus).values(
                    source=publication.source,
                    watermark=publication.watermark,
                    freshness_status="fresh",
                    last_success_at=now,
                    detail=publication.detail,
                )
                session.execute(
                    status.on_conflict_do_update(
                        index_elements=[DataSourceStatus.source],
                        set_={
                            "watermark": publication.watermark,
                            "freshness_status": "fresh",
                            "last_success_at": now,
                            "detail": publication.detail,
                        },
                    )
                )
                run.published_at = now

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
    ) -> bool:
        with self._sessions.begin() as session:
            run = self._owned_run(session, run_id, attempt)
            can_retry = retryable and attempt < run.max_attempts
            run.status = "retry" if can_retry else "dead_letter"
            run.error_code = error_code[:96]
            run.message = message[:2_000]
            run.completed_at = now
            run.heartbeat_at = now
            run.next_retry_at = next_retry_at if can_retry else None
            if not can_retry:
                run.dead_lettered_at = now
            status = insert(DataSourceStatus).values(
                source=run.source,
                freshness_status="degraded",
                last_failure_at=now,
                detail=run.message,
            )
            session.execute(
                status.on_conflict_do_update(
                    index_elements=[DataSourceStatus.source],
                    set_={
                        "freshness_status": "degraded",
                        "last_failure_at": now,
                        "detail": run.message,
                    },
                )
            )
            return can_retry

    def recover_stale(self, *, now: datetime, stale_after_seconds: int) -> int:
        cutoff = now - timedelta(seconds=stale_after_seconds)
        recovered = 0
        with self._sessions.begin() as session:
            runs = session.execute(
                select(RefreshRun)
                .where(RefreshRun.status == "running", RefreshRun.heartbeat_at < cutoff)
                .with_for_update(skip_locked=True)
            ).scalars()
            for run in runs:
                recovered += 1
                if run.attempt < run.max_attempts:
                    run.status = "retry"
                    run.next_retry_at = now
                    run.error_code = "stale_heartbeat"
                    run.message = "Recovered after heartbeat timeout"
                else:
                    run.status = "dead_letter"
                    run.dead_lettered_at = now
                    run.error_code = "stale_heartbeat"
                    run.message = "Heartbeat timeout exhausted attempts"
                run.completed_at = now
        return recovered

    @staticmethod
    def _owned_run(session: Session, run_id: int, attempt: int) -> RefreshRun:
        run = session.get(RefreshRun, run_id, with_for_update=True)
        if run is None or run.status != "running" or run.attempt != attempt:
            raise RuntimeError("task execution lease is no longer owned")
        return run

    def close(self) -> None:
        self._engine.dispose()
