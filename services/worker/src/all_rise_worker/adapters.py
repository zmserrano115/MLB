from __future__ import annotations

import json
import os
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from typing import Any, Protocol

from all_rise.domain.live import live_event_records, parse_live_game_feed
from all_rise.jobs import (
    Publication,
    QualityGateError,
    TaskContext,
    TaskResult,
)
from all_rise.jobs.artifacts import StoredArtifact
from all_rise.jobs.executor import TaskHandler
from all_rise.jobs.validation import SourceValidationIssue, validate_source_records

from all_rise_worker.providers import (
    MlbLiveFeedProvider,
    MlbScheduleProvider,
    OpenMeteoProvider,
    PostgresWeatherCandidates,
)


class ScheduleProvider(Protocol):
    def fetch(self, game_date: str, source_version: str) -> list[dict[str, Any]]: ...


class WeatherCandidates(Protocol):
    def fetch(self, start: str, end: str) -> list[dict[str, Any]]: ...


class WeatherProvider(Protocol):
    def forecast(self, candidate: Mapping[str, Any]) -> dict[str, Any]: ...


class LiveFeedProvider(Protocol):
    def fetch(self, game_pk: int) -> dict[str, Any]: ...


@dataclass(slots=True)
class PollLiveGameAdapter:
    provider: LiveFeedProvider

    def __call__(self, payload: dict[str, Any], context: TaskContext) -> TaskResult:
        game_id = _required_text(payload, "game_id")
        if not game_id.startswith("mlb:"):
            raise ValueError("game_id must use the canonical mlb:<game_pk> form")
        game_pk = int(game_id.removeprefix("mlb:"))
        snapshot = parse_live_game_feed(self.provider.fetch(game_pk), game_id)
        observed_at = context.clock().isoformat()
        snapshot["observed_at"] = observed_at
        encoded = json.dumps(snapshot, sort_keys=True, separators=(",", ":"), default=str).encode()
        if len(encoded) > 131_072:
            raise QualityGateError("compact live snapshot exceeds the 128 KiB payload budget")
        record = {
            "game_id": game_id,
            "version": snapshot["version"],
            "observed_at": observed_at,
            "feed_timestamp": snapshot.get("feed_timestamp"),
            "abstract_state": snapshot["abstract_state"],
            "detailed_state": snapshot["detailed_state"],
            "is_final": snapshot["is_final"],
            "payload_size_bytes": len(encoded),
            "snapshot": snapshot,
            "events": live_event_records(snapshot),
        }
        for event in record["events"]:
            event["source_updated_at"] = observed_at
        stored = context.put_artifact(
            source="mlb-live-feed",
            generation=str(snapshot["version"]),
            name=f"live-{game_pk}.json",
            data=encoded,
            source_version=str(snapshot["version"]),
            inventory={"events": len(record["events"]), "bytes": len(encoded)},
            content_type="application/json",
        )
        context.record_item(game_id, status="succeeded", payload={"final": snapshot["is_final"]})
        return TaskResult(
            payload={
                "artifact_uri": stored.uri,
                "version": snapshot["version"],
                "continue_polling": not snapshot["is_final"],
            },
            processed_items=1,
            facts_loaded=1 + len(record["events"]),
            publication=Publication(
                source="mlb-live-feed",
                scope=game_id,
                watermark=observed_at,
                source_version=str(snapshot["version"]),
                detail=f"Published compact live snapshot for {game_id}",
                dataset="live_game",
                records=(record,),
            ),
        )


@dataclass(slots=True)
class ScheduleAdapter:
    provider: ScheduleProvider

    def __call__(self, payload: dict[str, Any], context: TaskContext) -> TaskResult:
        game_date = _iso_date(payload.get("date"), "date")
        source_version = _required_text(payload, "source_version")
        records = self.provider.fetch(game_date, source_version)
        report = validate_source_records(
            records,
            identity_fields=("source_game_id",),
            required_fields=(
                "source_game_id",
                "mlb_game_pk",
                "game_date",
                "away_team",
                "home_team",
                "source_version",
            ),
        )
        issues = list(report.issues)
        for record in records:
            for side in ("away_team", "home_team"):
                team = record.get(side)
                if (
                    not isinstance(team, Mapping)
                    or not team.get("provider_team_id")
                    or not team.get("name")
                ):
                    issues.append(
                        SourceValidationIssue(
                            str(record.get("source_game_id") or "unknown"),
                            "invalid_team_identity",
                            f"{side} requires provider_team_id and name",
                        )
                    )
        if issues:
            for issue in issues:
                context.record_item(
                    issue.item_key,
                    status="failed",
                    error_code=issue.code,
                    message=issue.message,
                )
            raise QualityGateError(f"schedule validation failed for {len(issues)} records")
        stored = _artifact(
            context,
            source="mlb-statsapi",
            generation=source_version,
            name=f"schedule-{game_date}.json",
            records=records,
        )
        for record in records:
            context.record_item(
                str(record["source_game_id"]),
                status="succeeded",
                payload={"status": record.get("game_status")},
            )
        return TaskResult(
            payload={"mode": "active", "artifact_uri": stored.uri, "sha256": stored.sha256},
            processed_items=len(records),
            facts_loaded=len(records),
            publication=Publication(
                source="mlb-statsapi",
                scope=game_date,
                watermark=game_date,
                source_version=source_version,
                detail=f"Published {len(records)} schedule records",
                dataset="schedule",
                records=tuple(records),
            ),
        )


@dataclass(slots=True)
class WeatherAdapter:
    candidates: WeatherCandidates
    provider: WeatherProvider

    def __call__(self, payload: dict[str, Any], context: TaskContext) -> TaskResult:
        start = _iso_date(payload.get("start"), "start")
        end = _iso_date(payload.get("end"), "end")
        if end < start:
            raise ValueError("end must be on or after start")
        if (date.fromisoformat(end) - date.fromisoformat(start)).days > 7:
            raise ValueError("weather refresh windows cannot exceed 8 days")
        source_version = _required_text(payload, "source_version")
        observed_at = context.clock().isoformat()
        records: list[dict[str, Any]] = []
        failed = 0
        for candidate in self.candidates.fetch(start, end):
            item_key = str(candidate.get("source_game_id") or "unknown")
            try:
                forecast = self.provider.forecast(candidate)
            except QualityGateError as exc:
                failed += 1
                context.record_item(
                    item_key,
                    status="failed",
                    error_code=type(exc).__name__,
                    message=str(exc),
                )
                continue
            record = {
                "source_game_id": item_key,
                "observed_at": observed_at,
                "source": "Open-Meteo",
                "source_version": source_version,
                **forecast,
            }
            records.append(record)
            context.record_item(
                item_key,
                status="succeeded",
                payload={"forecast_for": record.get("forecast_for")},
            )
        report = validate_source_records(
            records,
            identity_fields=("source_game_id", "observed_at", "source"),
            required_fields=("source_game_id", "observed_at", "source", "forecast_for"),
        )
        for issue in report.issues:
            failed += 1
            context.record_item(
                issue.item_key,
                status="failed",
                error_code=issue.code,
                message=issue.message,
            )
        stored = _artifact(
            context,
            source="open-meteo",
            generation=source_version,
            name=f"weather-{start}-{end}.json",
            records=records,
        )
        max_failed = _nonnegative_int(payload.get("max_failed_items", 0))
        return TaskResult(
            payload={"mode": "active", "artifact_uri": stored.uri, "sha256": stored.sha256},
            processed_items=len(records),
            failed_items=failed,
            max_failed_items=max_failed,
            facts_loaded=len(records),
            publication=Publication(
                source="open-meteo",
                scope=f"{start}:{end}",
                watermark=observed_at,
                source_version=source_version,
                detail=f"Published {len(records)} weather snapshots; {failed} failed",
                dataset="weather",
                records=tuple(records),
            ),
        )


def build_adapters(database_url: str) -> dict[str, TaskHandler]:
    mlb_base = os.getenv("MLB_API_BASE_URL", "https://statsapi.mlb.com").rstrip("/")
    weather_base = os.getenv("WEATHER_API_BASE_URL", "https://api.open-meteo.com").rstrip("/")
    return {
        "refresh_schedule": ScheduleAdapter(
            MlbScheduleProvider(base_url=f"{mlb_base}/api/v1/schedule")
        ),
        "refresh_weather": WeatherAdapter(
            PostgresWeatherCandidates(database_url),
            OpenMeteoProvider(base_url=f"{weather_base}/v1/forecast"),
        ),
        "poll_live_game": PollLiveGameAdapter(MlbLiveFeedProvider()),
    }


def _artifact(
    context: TaskContext,
    *,
    source: str,
    generation: str,
    name: str,
    records: list[dict[str, Any]],
) -> StoredArtifact:
    encoded = json.dumps(
        {"records": records}, sort_keys=True, separators=(",", ":"), default=str
    ).encode()
    return context.put_artifact(
        source=source,
        generation=generation,
        name=name,
        data=encoded,
        source_version=generation,
        inventory={"records": len(records)},
        content_type="application/json",
    )


def _required_text(payload: Mapping[str, Any], field: str) -> str:
    value = str(payload.get(field) or "").strip()
    if not value:
        raise ValueError(f"{field} is required")
    return value


def _iso_date(value: Any, field: str) -> str:
    text = str(value or "").strip()
    try:
        return date.fromisoformat(text).isoformat()
    except ValueError as exc:
        raise ValueError(f"{field} must be an ISO date") from exc


def _nonnegative_int(value: Any) -> int:
    result = int(value)
    if result < 0:
        raise ValueError("max_failed_items cannot be negative")
    return result
