from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from all_rise.jobs import (
    ExecutionState,
    JobExecutor,
    Publication,
    RetryableTaskError,
    TaskRequest,
    TaskResult,
)
from all_rise.jobs.artifacts import ArtifactConflictError, LocalArtifactStore
from all_rise.jobs.contracts import ArtifactRecord, ClaimResult, ClaimState
from all_rise.jobs.statcast import correction_window, inclusive_windows, merge_corrections
from all_rise.jobs.validation import validate_source_records
from all_rise.models import Base
from all_rise_worker.actors.tasks import retry_only_when_scheduled
from all_rise_worker.catalog import TASK_SPECS, build_registry
from all_rise_worker.commands.run_task import canonical_idempotency_key


@dataclass
class MemoryRun:
    request: TaskRequest
    run_id: int
    attempt: int
    status: str
    heartbeat: datetime
    next_retry: datetime | None = None
    published: Publication | None = None


class MemoryJobStore:
    def __init__(self) -> None:
        self.runs: dict[str, MemoryRun] = {}
        self.items: list[dict[str, Any]] = []
        self.artifacts: list[ArtifactRecord] = []

    def claim(
        self,
        request: TaskRequest,
        *,
        now: datetime,
        stale_after_seconds: int,
    ) -> ClaimResult:
        run = self.runs.get(request.idempotency_key)
        if run is None:
            run = MemoryRun(request, len(self.runs) + 1, 1, "running", now)
            self.runs[request.idempotency_key] = run
            return ClaimResult(ClaimState.ACQUIRED, run.run_id, run.attempt)
        if run.request.task_name != request.task_name or run.request.payload != request.payload:
            raise ValueError("idempotency key reused")
        if run.status == "succeeded":
            return ClaimResult(ClaimState.DUPLICATE, run.run_id, run.attempt)
        if run.status == "running" and run.heartbeat >= now - timedelta(
            seconds=stale_after_seconds
        ):
            return ClaimResult(ClaimState.IN_PROGRESS, run.run_id, run.attempt)
        if run.next_retry and run.next_retry > now:
            return ClaimResult(ClaimState.IN_PROGRESS, run.run_id, run.attempt)
        if run.attempt >= request.max_attempts or run.status == "dead_letter":
            run.status = "dead_letter"
            return ClaimResult(ClaimState.DEAD_LETTER, run.run_id, run.attempt)
        run.attempt += 1
        run.status = "running"
        run.heartbeat = now
        run.next_retry = None
        return ClaimResult(ClaimState.ACQUIRED, run.run_id, run.attempt)

    def heartbeat(self, run_id: int, attempt: int, *, now: datetime) -> bool:
        run = self._run(run_id)
        if run.attempt != attempt or run.status != "running":
            return False
        run.heartbeat = now
        return True

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
    ) -> None:
        self.items.append(
            {
                "run_id": run_id,
                "attempt": attempt,
                "item_key": item_key,
                "status": status,
                "payload": payload,
                "error_code": error_code,
                "message": message,
                "now": now,
            }
        )

    def register_artifact(self, artifact: ArtifactRecord) -> None:
        self.artifacts.append(artifact)

    def succeed(
        self,
        run_id: int,
        attempt: int,
        result: TaskResult,
        *,
        now: datetime,
    ) -> None:
        run = self._owned(run_id, attempt)
        run.status = "succeeded"
        run.heartbeat = now
        run.published = result.publication

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
        del error_code, message
        run = self._owned(run_id, attempt)
        can_retry = retryable and attempt < run.request.max_attempts
        run.status = "retry" if can_retry else "dead_letter"
        run.next_retry = next_retry_at
        run.heartbeat = now
        return can_retry

    def recover_stale(self, *, now: datetime, stale_after_seconds: int) -> int:
        recovered = 0
        for run in self.runs.values():
            if run.status == "running" and run.heartbeat < now - timedelta(
                seconds=stale_after_seconds
            ):
                recovered += 1
                run.status = "retry" if run.attempt < run.request.max_attempts else "dead_letter"
                run.next_retry = now
        return recovered

    def close(self) -> None:
        return None

    def _run(self, run_id: int) -> MemoryRun:
        return next(run for run in self.runs.values() if run.run_id == run_id)

    def _owned(self, run_id: int, attempt: int) -> MemoryRun:
        run = self._run(run_id)
        if run.status != "running" or run.attempt != attempt:
            raise RuntimeError("lease lost")
        return run


def request(*, max_attempts: int = 3) -> TaskRequest:
    return TaskRequest(
        task_name="test_task",
        idempotency_key="test_task:version-1",
        source="fixture",
        scope="one",
        payload={"version": "1"},
        max_attempts=max_attempts,
    )


def executor(
    tmp_path: Path,
    store: MemoryJobStore,
    handler,
    *,
    now: list[datetime],
) -> JobExecutor:
    registry = build_test_registry(handler)
    return JobExecutor(
        store,
        LocalArtifactStore(tmp_path / "artifacts"),
        registry,
        stale_after_seconds=60,
        clock=lambda: now[0],
    )


def build_test_registry(handler):
    from all_rise.jobs import TaskRegistry

    registry = TaskRegistry()
    registry.register("test_task", handler)
    return registry


def test_duplicate_delivery_executes_handler_once(tmp_path: Path) -> None:
    store = MemoryJobStore()
    now = [datetime(2026, 7, 13, tzinfo=UTC)]
    calls = 0

    def handler(payload, context):
        nonlocal calls
        del payload, context
        calls += 1
        return TaskResult(processed_items=1)

    jobs = executor(tmp_path, store, handler, now=now)
    assert jobs.execute(request()).state is ExecutionState.SUCCEEDED
    assert jobs.execute(request()).state is ExecutionState.DUPLICATE
    assert calls == 1


def test_retry_is_bounded_and_enters_dead_letter(tmp_path: Path) -> None:
    store = MemoryJobStore()
    now = [datetime(2026, 7, 13, tzinfo=UTC)]

    def handler(payload, context):
        del payload, context
        raise RetryableTaskError("provider throttled")

    jobs = executor(tmp_path, store, handler, now=now)
    first = jobs.execute(request(max_attempts=2))
    assert first.state is ExecutionState.RETRY
    now[0] += timedelta(milliseconds=first.retry_delay_ms or 0, seconds=1)
    second = jobs.execute(request(max_attempts=2))
    assert second.state is ExecutionState.DEAD_LETTER
    assert store.runs[request().idempotency_key].attempt == 2


def test_stale_crash_is_recovered_without_concurrent_duplicate(tmp_path: Path) -> None:
    store = MemoryJobStore()
    now = [datetime(2026, 7, 13, tzinfo=UTC)]
    claimed = store.claim(request(), now=now[0], stale_after_seconds=60)
    assert claimed.state is ClaimState.ACQUIRED
    duplicate = store.claim(request(), now=now[0], stale_after_seconds=60)
    assert duplicate.state is ClaimState.IN_PROGRESS

    now[0] += timedelta(seconds=61)
    jobs = executor(tmp_path, store, lambda payload, context: TaskResult(), now=now)
    assert jobs.recover_stale() == 1
    assert jobs.execute(request()).state is ExecutionState.SUCCEEDED
    assert store.runs[request().idempotency_key].attempt == 2


def test_partial_failure_cannot_publish_generation(tmp_path: Path) -> None:
    store = MemoryJobStore()
    now = [datetime(2026, 7, 13, tzinfo=UTC)]
    publication = Publication("statcast", "window", "2026-07-13", "v1")

    def handler(payload, context):
        del payload
        context.record_item("game-1", status="failed", error_code="bad_source")
        return TaskResult(failed_items=1, max_failed_items=0, publication=publication)

    result = executor(tmp_path, store, handler, now=now).execute(request())
    assert result.state is ExecutionState.DEAD_LETTER
    assert store.runs[request().idempotency_key].published is None
    assert store.items[0]["error_code"] == "bad_source"


def test_local_artifacts_are_immutable_and_idempotent(tmp_path: Path) -> None:
    artifacts = LocalArtifactStore(tmp_path)
    first = artifacts.put_bytes(source="statcast", generation="v1", name="raw.json", data=b"one")
    replay = artifacts.put_bytes(source="statcast", generation="v1", name="raw.json", data=b"one")
    assert replay.sha256 == first.sha256
    with pytest.raises(ArtifactConflictError):
        artifacts.put_bytes(source="statcast", generation="v1", name="raw.json", data=b"two")
    with pytest.raises(ValueError):
        artifacts.put_bytes(source="statcast", generation="v1", name="../escape", data=b"x")


def test_statcast_multi_window_merge_matches_single_window() -> None:
    old = {
        "game_pk": 1,
        "at_bat_number": 1,
        "pitch_number": 1,
        "description": "old",
        "source_updated_at": "2026-07-10T00:00:00Z",
    }
    corrected = {**old, "description": "corrected", "source_updated_at": "2026-07-13T00:00:00Z"}
    second = {
        "game_pk": 2,
        "at_bat_number": 1,
        "pitch_number": 1,
        "source_updated_at": "2026-07-12T00:00:00Z",
    }
    single = merge_corrections([old], [[corrected, second]])
    chunked = merge_corrections([old], [[corrected], [second]])
    assert single == chunked
    assert single[0]["description"] == "corrected"
    assert list(inclusive_windows(date(2026, 7, 1), date(2026, 7, 8), chunk_days=3)) == [
        (date(2026, 7, 1), date(2026, 7, 3)),
        (date(2026, 7, 4), date(2026, 7, 6)),
        (date(2026, 7, 7), date(2026, 7, 8)),
    ]
    assert correction_window(date(2026, 7, 13), recheck_days=4) == (
        date(2026, 7, 10),
        date(2026, 7, 13),
    )


def test_task_catalog_and_shadow_ownership_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    expected = {
        "refresh_schedule",
        "refresh_probable_pitchers",
        "refresh_roster",
        "refresh_injuries",
        "process_completed_game",
        "refresh_weather",
        "poll_live_game",
        "persist_live_snapshot",
        "refresh_statcast_window",
        "import_retrosheet_season",
        "rebuild_bvp_keys",
        "rebuild_pitch_type_keys",
        "generate_bullpen_projection",
        "refresh_streak_summaries",
        "validate_data_source",
        "cleanup_retention",
        "warm_cache",
    }
    assert set(TASK_SPECS) == expected
    monkeypatch.setenv("JOB_SOURCE_OWNERSHIP", "active")
    store = MemoryJobStore()
    now = [datetime(2026, 7, 13, tzinfo=UTC)]
    jobs = JobExecutor(
        store,
        LocalArtifactStore(tmp_path),
        build_registry(),
        clock=lambda: now[0],
    )
    result = jobs.execute(
        TaskRequest(
            "refresh_schedule",
            "schedule:2026-07-13:v1",
            "mlb-statsapi",
            "2026-07-13",
            {"date": "2026-07-13", "source_version": "v1"},
        )
    )
    assert result.state is ExecutionState.DEAD_LETTER
    assert "no active source adapter" in (result.message or "")


def test_canonical_keys_ignore_json_field_order_and_schema_is_phase6() -> None:
    assert canonical_idempotency_key("x", {"a": 1, "b": 2}) == canonical_idempotency_key(
        "x", {"b": 2, "a": 1}
    )
    assert "refresh_run_items" in Base.metadata.tables
    assert Base.metadata.tables["refresh_runs"].c.idempotency_key.unique


def test_source_validation_reports_missing_and_duplicate_rows() -> None:
    report = validate_source_records(
        [
            {"game_id": "mlb:1", "status": "Final"},
            {"game_id": "mlb:1", "status": "Final"},
            {"game_id": "mlb:2", "status": ""},
        ],
        identity_fields=("game_id",),
        required_fields=("game_id", "status"),
    )
    assert report.checked == 3
    assert report.accepted == 1
    assert [issue.code for issue in report.issues] == [
        "duplicate_identity",
        "missing_required_field",
    ]


def test_dramatiq_only_requeues_database_scheduled_retry() -> None:
    import dramatiq

    assert retry_only_when_scheduled(10, dramatiq.Retry("later", delay=1_000))
    assert not retry_only_when_scheduled(0, RuntimeError("dead letter"))
