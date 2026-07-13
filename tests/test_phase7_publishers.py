from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from all_rise.jobs import ExecutionState, JobExecutor, TaskRequest
from all_rise.jobs.artifacts import LocalArtifactStore
from all_rise_worker.adapters import ScheduleAdapter, WeatherAdapter
from all_rise_worker.catalog import build_registry
from all_rise_worker.providers import MlbScheduleProvider, OpenMeteoProvider
from test_phase6_jobs import MemoryJobStore


class FixtureSchedule:
    def fetch(self, game_date: str, source_version: str) -> list[dict[str, Any]]:
        return [
            {
                "source_game_id": "mlb:746123",
                "mlb_game_pk": 746123,
                "game_date": game_date,
                "season": 2026,
                "game_time_utc": f"{game_date}T20:10:00Z",
                "game_status": "Preview",
                "away_score": None,
                "home_score": None,
                "away_team": {
                    "provider_team_id": 110,
                    "name": "Baltimore Orioles",
                    "abbreviation": "BAL",
                },
                "home_team": {
                    "provider_team_id": 147,
                    "name": "New York Yankees",
                    "abbreviation": "NYY",
                },
                "away_probable_pitcher": {
                    "provider_player_id": 1,
                    "name": "Away Starter",
                },
                "home_probable_pitcher": {
                    "provider_player_id": 2,
                    "name": "Home Starter",
                },
                "venue": {
                    "provider_venue_id": 3313,
                    "name": "Yankee Stadium",
                    "city": "Bronx",
                    "latitude": 40.8296,
                    "longitude": -73.9262,
                    "elevation_ft": 55,
                    "roof_type": "Open",
                    "center_field_azimuth": 76,
                },
                "source_version": source_version,
            }
        ]


class FixtureCandidates:
    def fetch(self, start: str, end: str) -> list[dict[str, Any]]:
        assert start == end == "2026-07-13"
        return [
            {
                "source_game_id": "mlb:746123",
                "game_date": start,
                "game_time_utc": "2026-07-13T20:10:00Z",
                "latitude": 40.8296,
                "longitude": -73.9262,
                "roof_type": "Open",
                "center_field_azimuth": 76,
            }
        ]


class FixtureWeather:
    def forecast(self, candidate):
        assert candidate["source_game_id"] == "mlb:746123"
        return {
            "forecast_for": "2026-07-13T20:00:00+00:00",
            "condition": "Clear",
            "temperature_f": 82.0,
            "feels_like_f": 83.0,
            "humidity_percent": 45.0,
            "wind_speed_mph": 10.0,
            "wind_direction_degrees": 256.0,
            "wind_out_mph": 10.0,
            "precipitation_probability": 5.0,
            "hitter_adjustment": 3.5,
            "pitcher_adjustment": -0.7,
            "edge_label": "Strong hitter boost",
            "stale": False,
            "provider_residual": {"weather_code": 0},
        }


def _executor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    task_name: str,
    adapter,
):
    monkeypatch.setenv("JOB_SOURCE_OWNERSHIP", "shadow")
    monkeypatch.setenv("JOB_ACTIVE_TASKS", task_name)
    store = MemoryJobStore()
    jobs = JobExecutor(
        store,
        LocalArtifactStore(tmp_path / "artifacts"),
        build_registry({task_name: adapter}),
        clock=lambda: datetime(2026, 7, 13, 16, 0, tzinfo=UTC),
    )
    return jobs, store


def test_active_schedule_adapter_is_idempotent_and_builds_atomic_publication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    jobs, store = _executor(
        tmp_path, monkeypatch, "refresh_schedule", ScheduleAdapter(FixtureSchedule())
    )
    request = TaskRequest(
        "refresh_schedule",
        "schedule:2026-07-13:fixture-v1",
        "mlb-statsapi",
        "2026-07-13",
        {"date": "2026-07-13", "source_version": "fixture-v1"},
    )
    assert jobs.execute(request).state is ExecutionState.SUCCEEDED
    assert jobs.execute(request).state is ExecutionState.DUPLICATE
    run = store.runs[request.idempotency_key]
    assert run.published is not None
    assert run.published.dataset == "schedule"
    assert run.published.records[0]["source_game_id"] == "mlb:746123"
    assert len(store.items) == 1
    assert len(store.artifacts) == 1


def test_active_weather_adapter_builds_safe_snapshot_publication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    jobs, store = _executor(
        tmp_path,
        monkeypatch,
        "refresh_weather",
        WeatherAdapter(FixtureCandidates(), FixtureWeather()),
    )
    request = TaskRequest(
        "refresh_weather",
        "weather:2026-07-13:fixture-v1",
        "open-meteo",
        "2026-07-13",
        {"start": "2026-07-13", "end": "2026-07-13", "source_version": "fixture-v1"},
    )
    assert jobs.execute(request).state is ExecutionState.SUCCEEDED
    publication = store.runs[request.idempotency_key].published
    assert publication is not None
    assert publication.dataset == "weather"
    assert publication.records[0]["source"] == "Open-Meteo"
    assert publication.records[0]["provider_residual"] == {"weather_code": 0}


def test_weather_quality_failure_never_publishes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class MissingCoordinates:
        def fetch(self, start: str, end: str) -> list[dict[str, Any]]:
            return [{"source_game_id": "mlb:missing", "game_date": start}]

    jobs, store = _executor(
        tmp_path,
        monkeypatch,
        "refresh_weather",
        WeatherAdapter(MissingCoordinates(), OpenMeteoProvider()),
    )
    request = TaskRequest(
        "refresh_weather",
        "weather:missing:v1",
        "open-meteo",
        "2026-07-13",
        {"start": "2026-07-13", "end": "2026-07-13", "source_version": "v1"},
    )
    result = jobs.execute(request)
    assert result.state is ExecutionState.DEAD_LETTER
    assert store.runs[request.idempotency_key].published is None
    assert store.items[0]["status"] == "failed"


def test_provider_normalization_matches_persisted_contract() -> None:
    class ScheduleHttp:
        def get(self, url, params, *, provider):
            assert params["date"] == "2026-07-13"
            return {
                "dates": [
                    {
                        "games": [
                            {
                                "gamePk": 746123,
                                "gameDate": "2026-07-13T20:10:00Z",
                                "status": {"detailedState": "Scheduled"},
                                "teams": {
                                    "away": {"team": {"id": 110, "name": "Orioles"}},
                                    "home": {"team": {"id": 147, "name": "Yankees"}},
                                },
                                "venue": {"id": 3313, "name": "Yankee Stadium"},
                            }
                        ]
                    }
                ]
            }

    record = MlbScheduleProvider(ScheduleHttp()).fetch("2026-07-13", "v1")[0]
    assert record["source_game_id"] == "mlb:746123"
    assert record["away_team"]["provider_team_id"] == 110
    assert record["source_version"] == "v1"


def test_open_meteo_selects_nearest_hour_and_calculates_field_weather() -> None:
    class WeatherHttp:
        def get(self, url, params, *, provider):
            return {
                "hourly": {
                    "time": ["2026-07-13T19:00", "2026-07-13T20:00"],
                    "temperature_2m": [80, 82],
                    "apparent_temperature": [81, 83],
                    "relative_humidity_2m": [50, 45],
                    "precipitation_probability": [10, 5],
                    "surface_pressure": [1000, 1001],
                    "wind_speed_10m": [8, 10],
                    "wind_direction_10m": [256, 256],
                    "weather_code": [1, 0],
                }
            }

    result = OpenMeteoProvider(WeatherHttp()).forecast(
        {
            "source_game_id": "mlb:746123",
            "game_date": "2026-07-13",
            "game_time_utc": "2026-07-13T20:10:00Z",
            "latitude": 40.8296,
            "longitude": -73.9262,
            "roof_type": "Open",
            "center_field_azimuth": 76,
        }
    )
    assert result["forecast_for"] == "2026-07-13T20:00:00+00:00"
    assert result["condition"] == "Clear"
    assert result["temperature_f"] == 82.0
    assert result["wind_out_mph"] == pytest.approx(10.0)
    assert result["hitter_adjustment"] > 0
