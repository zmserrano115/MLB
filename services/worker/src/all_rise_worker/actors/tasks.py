from __future__ import annotations

from typing import Any

import dramatiq
from all_rise.jobs import ExecutionState, TaskRequest

from all_rise_worker.broker import broker as broker
from all_rise_worker.runtime import get_executor


def retry_only_when_scheduled(retries: int, exception: BaseException) -> bool:
    del retries
    return isinstance(exception, dramatiq.Retry)


@dramatiq.actor(retry_when=retry_only_when_scheduled)
def execute_task(
    task_name: str,
    idempotency_key: str,
    source: str,
    scope: str,
    payload: dict[str, Any],
    max_attempts: int = 5,
) -> None:
    result = get_executor().execute(
        TaskRequest(
            task_name=task_name,
            idempotency_key=idempotency_key,
            source=source,
            scope=scope,
            payload=payload,
            max_attempts=max_attempts,
        )
    )
    if result.state is ExecutionState.RETRY:
        raise dramatiq.Retry(
            result.message or "retryable task failure", delay=result.retry_delay_ms
        )
    if result.state is ExecutionState.DEAD_LETTER:
        raise RuntimeError(result.message or "task entered dead letter state")


@dramatiq.actor(max_retries=0)
def recover_stale_tasks() -> None:
    get_executor().recover_stale()
