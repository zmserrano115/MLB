from __future__ import annotations

import json
import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from all_rise.jobs import QualityGateError, TaskContext, TaskRegistry, TaskResult
from all_rise.jobs.executor import TaskHandler


@dataclass(frozen=True, slots=True)
class TaskSpec:
    source: str
    required_fields: tuple[str, ...]


TASK_SPECS: dict[str, TaskSpec] = {
    "refresh_schedule": TaskSpec("mlb-statsapi", ("date", "source_version")),
    "refresh_probable_pitchers": TaskSpec("mlb-statsapi", ("date", "source_version")),
    "refresh_roster": TaskSpec("mlb-statsapi", ("team_id", "date", "source_version")),
    "refresh_injuries": TaskSpec("mlb-statsapi", ("team_id", "date", "source_version")),
    "process_completed_game": TaskSpec("mlb-statsapi", ("game_id", "source_version")),
    "refresh_weather": TaskSpec("open-meteo", ("start", "end", "source_version")),
    "poll_live_game": TaskSpec("mlb-statsapi", ("game_id", "feed_timestamp")),
    "persist_live_snapshot": TaskSpec("mlb-statsapi", ("game_id", "version")),
    "refresh_statcast_window": TaskSpec("statcast", ("start", "end", "source_version")),
    "import_retrosheet_season": TaskSpec(
        "retrosheet", ("season", "artifact_generation")
    ),
    "rebuild_bvp_keys": TaskSpec("derived-bvp", ("keys", "generation")),
    "rebuild_pitch_type_keys": TaskSpec("derived-pitch-type", ("keys", "generation")),
    "generate_bullpen_projection": TaskSpec(
        "derived-bullpen", ("game_id", "team_id", "version")
    ),
    "refresh_streak_summaries": TaskSpec(
        "derived-streaks", ("season", "through_date", "version")
    ),
    "validate_data_source": TaskSpec("validation", ("source", "watermark")),
    "cleanup_retention": TaskSpec("retention", ("policy_version", "through_date")),
    "warm_cache": TaskSpec("cache", ("data_version",)),
}


def build_registry(adapters: Mapping[str, TaskHandler] | None = None) -> TaskRegistry:
    registry = TaskRegistry()
    for name, spec in TASK_SPECS.items():
        adapter = (adapters or {}).get(name)
        registry.register(
            name,
            (
                adapter
                if adapter is not None and _ownership_for(name) == "active"
                else _shadow_handler(name, spec)
            ),
        )
    return registry


def _ownership_for(name: str) -> str:
    ownership = os.getenv("JOB_SOURCE_OWNERSHIP", "shadow").strip().lower()
    active_tasks = {
        task.strip()
        for task in os.getenv("JOB_ACTIVE_TASKS", "").split(",")
        if task.strip()
    }
    return "active" if ownership == "active" or name in active_tasks else "shadow"


def _shadow_handler(
    name: str, spec: TaskSpec
) -> Callable[[dict[str, Any], TaskContext], TaskResult]:
    def execute(payload: dict[str, Any], context: TaskContext) -> TaskResult:
        missing = [
            field
            for field in spec.required_fields
            if payload.get(field) is None or payload.get(field) == ""
        ]
        if missing:
            raise ValueError(f"missing required task fields: {', '.join(missing)}")
        ownership = _ownership_for(name)
        if ownership != "shadow":
            raise QualityGateError(
                f"{name} has no active source adapter; keep JOB_SOURCE_OWNERSHIP=shadow"
            )
        generation = str(payload.get("source_version") or payload.get("generation") or "shadow")
        receipt = {
            "task": name,
            "source": spec.source,
            "ownership": ownership,
            "captured_at": datetime.now(UTC).isoformat(),
            "payload": payload,
        }
        encoded = json.dumps(receipt, sort_keys=True, separators=(",", ":")).encode()
        stored = context.put_artifact(
            source=f"shadow-{spec.source}",
            generation=generation,
            name=f"run-{context.run_id}-attempt-{context.attempt}.json",
            data=encoded,
            source_version=generation,
            inventory={"task": name, "ownership": ownership},
            content_type="application/json",
        )
        context.record_item(
            str(payload.get("game_id") or payload.get("team_id") or payload.get("date") or "scope"),
            status="succeeded",
            payload={"artifact_uri": stored.uri, "sha256": stored.sha256},
        )
        return TaskResult(
            payload={
                "mode": "shadow",
                "artifact_uri": stored.uri,
                "sha256": stored.sha256,
            },
            processed_items=1,
        )

    return execute
