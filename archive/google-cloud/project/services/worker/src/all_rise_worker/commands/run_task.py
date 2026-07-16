from __future__ import annotations

import argparse
import json
import os
from hashlib import sha256
from typing import Any

from all_rise.jobs import ExecutionState, TaskRequest

from all_rise_worker.catalog import TASK_SPECS
from all_rise_worker.runtime import get_executor


def canonical_idempotency_key(task_name: str, payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return f"{task_name}:{sha256(encoded).hexdigest()}"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run one durable All Rise batch task.")
    parser.add_argument("task_name", choices=sorted(TASK_SPECS))
    parser.add_argument("--payload", default=os.getenv("TASK_PAYLOAD", "{}"))
    parser.add_argument("--idempotency-key", default=os.getenv("TASK_IDEMPOTENCY_KEY"))
    parser.add_argument("--source")
    parser.add_argument("--scope", default="global")
    parser.add_argument("--max-attempts", type=int, default=int(os.getenv("JOB_MAX_ATTEMPTS", "5")))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    payload = json.loads(args.payload)
    if not isinstance(payload, dict):
        raise SystemExit("--payload must be a JSON object")
    source = args.source or TASK_SPECS[args.task_name].source
    request = TaskRequest(
        task_name=args.task_name,
        idempotency_key=args.idempotency_key
        or canonical_idempotency_key(args.task_name, payload),
        source=source,
        scope=args.scope,
        payload=payload,
        max_attempts=args.max_attempts,
    )
    result = get_executor().execute(request)
    print(json.dumps({"state": result.state, "run_id": result.run_id, "attempt": result.attempt}))
    return 0 if result.state in {ExecutionState.SUCCEEDED, ExecutionState.DUPLICATE} else 1


if __name__ == "__main__":
    raise SystemExit(main())
