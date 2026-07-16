from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from all_rise.application.live import LiveService
from all_rise.cache.versioned import CacheLoadResult, CacheOutcome
from all_rise.domain.live import parse_live_game_feed
from all_rise.jobs import ExecutionState, JobExecutor, TaskRequest
from all_rise.jobs.artifacts import LocalArtifactStore
from all_rise.repositories.protocols import LiveSnapshotRecord
from all_rise_api.dependencies import get_live_service
from all_rise_api.main import create_app
from all_rise_worker.adapters import PollLiveGameAdapter
from all_rise_worker.catalog import build_registry
from fastapi.testclient import TestClient
from test_phase3_api import settings
from test_phase6_jobs import MemoryJobStore


def feed(state: str = "Live", timestamp: str = "20260713_201500") -> dict[str, Any]:
    return {
        "metaData": {"timeStamp": timestamp},
        "gameData": {
            "status": {"abstractGameState": state, "detailedState": state},
            "teams": {
                "away": {"id": 147, "name": "New York Yankees", "abbreviation": "NYY"},
                "home": {"id": 115, "name": "Colorado Rockies", "abbreviation": "COL"},
            },
        },
        "liveData": {
            "linescore": {
                "currentInning": 5,
                "currentInningOrdinal": "5th",
                "inningHalf": "Top",
                "balls": 1,
                "strikes": 2,
                "outs": 1,
                "teams": {
                    "away": {"runs": 3, "hits": 7, "errors": 0},
                    "home": {"runs": 2, "hits": 5, "errors": 1},
                },
                "offense": {"first": {"id": 9}, "batter": {"id": 99, "fullName": "Aaron Judge"}},
                "defense": {"pitcher": {"id": 55, "fullName": "Starter"}},
            },
            "plays": {
                "allPlays": [
                    {
                        "about": {
                            "atBatIndex": 18,
                            "inning": 5,
                            "halfInning": "top",
                            "isComplete": True,
                        },
                        "result": {
                            "event": "Single",
                            "eventType": "single",
                            "description": "Judge singles to center.",
                            "awayScore": 3,
                            "homeScore": 2,
                        },
                        "matchup": {
                            "batter": {"id": 99, "fullName": "Aaron Judge"},
                            "pitcher": {"id": 55, "fullName": "Starter"},
                        },
                        "hitData": {"launchSpeed": 104.2, "launchAngle": 12, "totalDistance": 301},
                    }
                ],
                "currentPlay": {
                    "matchup": {
                        "batter": {"id": 99, "fullName": "Aaron Judge"},
                        "pitcher": {"id": 55, "fullName": "Starter"},
                    },
                    "playEvents": [
                        {
                            "isPitch": True,
                            "index": 1,
                            "details": {
                                "description": "Foul",
                                "isStrike": True,
                                "type": {"code": "FF", "description": "Four-Seam Fastball"},
                            },
                            "count": {"balls": 1, "strikes": 2, "outs": 1},
                            "pitchData": {"startSpeed": 97.1},
                        }
                    ],
                },
            },
            "boxscore": {"teams": {"away": {}, "home": {}}},
        },
    }


class FeedProvider:
    def __init__(self, state: str = "Live") -> None:
        self.calls = 0
        self.state = state

    def fetch(self, game_pk: int) -> dict[str, Any]:
        assert game_pk == 746123
        self.calls += 1
        return feed(self.state)


def test_recorded_replay_is_bounded_and_versions_progress() -> None:
    live = parse_live_game_feed(feed(), "mlb:746123")
    final = parse_live_game_feed(feed("Final", "20260713_231500"), "mlb:746123")
    assert live["version"] != final["version"]
    assert final["is_final"] is True
    assert live["recent_plays"][0]["result_type"] == "single"
    assert len(live["pitches"]) <= 12 and len(live["recent_plays"]) <= 8
    assert len(json.dumps(live).encode()) < 131_072


@pytest.mark.parametrize(("state", "continues"), [("Live", True), ("Final", False)])
def test_worker_fetches_once_and_final_stops(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, state: str, continues: bool
) -> None:
    monkeypatch.setenv("JOB_SOURCE_OWNERSHIP", "shadow")
    monkeypatch.setenv("JOB_ACTIVE_TASKS", "poll_live_game")
    provider = FeedProvider(state)
    store = MemoryJobStore()
    jobs = JobExecutor(
        store,
        LocalArtifactStore(tmp_path / "artifacts"),
        build_registry({"poll_live_game": PollLiveGameAdapter(provider)}),
        clock=lambda: datetime(2026, 7, 13, 20, 15, tzinfo=UTC),
    )
    result = jobs.execute(
        TaskRequest(
            "poll_live_game",
            f"live:{state}",
            "mlb-live-feed",
            "mlb:746123",
            {"game_id": "mlb:746123"},
        )
    )
    assert result.state is ExecutionState.SUCCEEDED
    assert result.result_payload and result.result_payload["continue_polling"] is continues
    assert provider.calls == 1
    publication = store.runs[f"live:{state}"].published
    assert publication and publication.dataset == "live_game"
    assert publication.records[0]["payload_size_bytes"] <= 131_072


class LiveRepository:
    def __init__(self) -> None:
        snapshot = parse_live_game_feed(feed("Final"), "mlb:746123")
        snapshot["observed_at"] = "2026-07-13T23:15:00+00:00"
        self.record = LiveSnapshotRecord(
            "mlb:746123",
            snapshot["version"],
            snapshot["observed_at"],
            True,
            len(json.dumps(snapshot).encode()),
            snapshot,
        )

    def get_live_snapshot(self, game_id: str) -> LiveSnapshotRecord | None:
        return self.record if game_id == self.record.game_id else None


class LiveCache:
    def __init__(self, degraded: bool = False) -> None:
        self.degraded = degraded

    def get_or_load(self, key, loader, *, ttl_seconds, negative_ttl_seconds):
        del key, ttl_seconds, negative_ttl_seconds
        return CacheLoadResult(
            loader(), CacheOutcome.DEGRADED if self.degraded else CacheOutcome.MISS, self.degraded
        )


def test_conditional_live_api_and_redis_failure_fallback() -> None:
    app = create_app(settings(schema_revision="0006_phase8_live_game"))
    app.dependency_overrides[get_live_service] = lambda: LiveService(
        LiveRepository(), LiveCache(degraded=True)
    )  # type: ignore[arg-type]
    with TestClient(app) as client:
        first = client.get("/api/v1/games/mlb:746123/live")
        by_since = client.get(
            f"/api/v1/games/mlb:746123/live?since={first.json()['data']['version']}"
        )
        by_etag = client.get(
            "/api/v1/games/mlb:746123/live", headers={"if-none-match": first.headers["etag"]}
        )
        missing = client.get("/api/v1/games/mlb:0/live")
    assert first.status_code == 200 and first.headers["x-cache-status"] == "degraded"
    assert first.json()["meta"]["stale"] is True
    assert by_since.status_code == by_etag.status_code == 304
    assert missing.status_code == 404
