from __future__ import annotations

from all_rise.application.research import ResearchService
from all_rise.cache.versioned import CacheLoadResult, CacheOutcome
from all_rise.repositories.protocols import (
    BatterPitcherMatchupRecord,
    BattingSummaryRecord,
    PitchingSummaryRecord,
    PlayerGameLogRecord,
    PlayerRecord,
)
from all_rise_api.dependencies import get_research_service
from all_rise_api.main import create_app
from fastapi.testclient import TestClient
from test_phase3_api import settings


class FakeResearchRepository:
    player = PlayerRecord(
        player_id="592450",
        name="Aaron Judge",
        active_status="active",
        player_type="batter",
        latest_season=2026,
        last_game_date="2026-07-12",
    )
    batter = BattingSummaryRecord(
        season=2026,
        games=80,
        pa=350,
        ab=300,
        hits=96,
        doubles=18,
        triples=1,
        walks=45,
        hit_by_pitch=5,
        strikeouts=82,
        home_runs=31,
        rbi=70,
        total_bases=209,
        batting_average=0.32,
        on_base_percentage=0.41714,
        slugging_percentage=0.69667,
    )
    pitcher = PitchingSummaryRecord(
        season=2026,
        games=18,
        starts=18,
        innings_outs=324,
        pitch_count=1700,
        batters_faced=430,
        hits=80,
        walks=25,
        hit_by_pitch=4,
        strikeouts=125,
        home_runs=12,
        runs=38,
        earned_runs=34,
        earned_run_average=2.83,
        whip=0.97,
    )
    log = PlayerGameLogRecord(
        game_id="mlb:746123",
        game_date="2026-07-12",
        season=2026,
        group="batting",
        opponent="Chicago Cubs",
        pa=4,
        ab=3,
        hits=2,
        walks=1,
        strikeouts=1,
        home_runs=1,
        rbi=2,
        total_bases=5,
    )
    matchup = BatterPitcherMatchupRecord(
        batter_id="592450",
        batter_name="Aaron Judge",
        pitcher_id="543037",
        pitcher_name="Gerrit Cole",
        season=2026,
        games=3,
        pa=10,
        ab=9,
        hits=3,
        doubles=1,
        triples=0,
        walks=1,
        hit_by_pitch=0,
        strikeouts=4,
        home_runs=1,
        rbi=2,
        total_bases=7,
        batting_average=0.33333,
        on_base_percentage=0.4,
        slugging_percentage=0.77778,
        last_game_date="2026-07-12",
    )

    def get_data_version(self) -> str:
        return "stats:2026-07-13"

    def get_players(self, **kwargs) -> list[PlayerRecord]:
        del kwargs
        return [self.player, self.player]

    def get_player(self, player_id: str) -> PlayerRecord | None:
        return self.player if player_id == self.player.player_id else None

    def get_player_batting_summary(self, player_id: str, *, season: int | None):
        del player_id, season
        return self.batter

    def get_player_pitching_summary(self, player_id: str, *, season: int | None):
        del player_id, season
        return None

    def get_player_game_logs(self, player_id: str, **kwargs):
        del player_id, kwargs
        return [self.log]

    def get_batter_pitcher_matchup(self, **kwargs):
        return self.matchup if kwargs["pitcher_id"] == "543037" else None

    def get_batter_pitcher_logs(self, **kwargs):
        del kwargs
        return [self.log]


class FakeCache:
    def ping(self) -> bool:
        return True

    def get_or_load(self, key, loader, *, ttl_seconds, negative_ttl_seconds):
        del key, ttl_seconds, negative_ttl_seconds
        return CacheLoadResult(loader(), CacheOutcome.MISS)

    def close(self) -> None:
        return None


def research_client() -> TestClient:
    app = create_app(settings(schema_revision="0004_slate_weather_read_models"))
    service = ResearchService(FakeResearchRepository(), FakeCache())
    app.dependency_overrides[get_research_service] = lambda: service
    return TestClient(app)


def test_player_directory_is_bounded_paginated_and_conditional() -> None:
    with research_client() as client:
        response = client.get("/api/v1/players?query=judge&role=batter&limit=1")
        conditional = client.get(
            "/api/v1/players?query=judge&role=batter&limit=1",
            headers={"if-none-match": response.headers["etag"]},
        )

    assert response.status_code == 200
    assert response.json()["data"][0]["player_id"] == "592450"
    assert response.json()["meta"]["pagination"]["next_cursor"] == "592450"
    assert conditional.status_code == 304


def test_player_profile_returns_persisted_summary_and_logs() -> None:
    with research_client() as client:
        response = client.get("/api/v1/players/592450?season=2026&group=batting")
        missing = client.get("/api/v1/players/1")

    assert response.status_code == 200
    assert response.json()["data"]["batting"]["home_runs"] == 31
    assert response.json()["data"]["game_logs"][0]["game_id"] == "mlb:746123"
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "player_not_found"


def test_batter_pitcher_matchup_returns_summary_and_history() -> None:
    with research_client() as client:
        response = client.get(
            "/api/v1/matchups/batter-vs-pitcher?batter_id=592450&pitcher_id=543037&season=2026"
        )
        missing = client.get("/api/v1/matchups/batter-vs-pitcher?batter_id=592450&pitcher_id=1")

    assert response.status_code == 200
    assert response.json()["data"]["batting_average"] == 0.33333
    assert len(response.json()["data"]["game_logs"]) == 1
    assert missing.status_code == 404


def test_research_query_validation_rejects_unbounded_or_unsafe_inputs() -> None:
    with research_client() as client:
        bad_role = client.get("/api/v1/players?role=catcher")
        bad_id = client.get("/api/v1/players/not-a-number")
        bad_limit = client.get(
            "/api/v1/matchups/batter-vs-pitcher?batter_id=1&pitcher_id=2&limit=101"
        )

    assert bad_role.status_code == 422
    assert bad_id.status_code == 422
    assert bad_limit.status_code == 422
