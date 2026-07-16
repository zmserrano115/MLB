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

    def get_advanced_matchup(self, **kwargs):
        del kwargs
        return {
            "coverage": {"pitch_count": 12, "games": 2, "last_game_date": "2026-07-12"},
            "pitch_types": [],
            "sequences": [],
        }

    def get_pitcher_opponent(self, **kwargs):
        del kwargs
        return {"splits": [], "game_logs": []}

    def get_bullpen_projection(self, **kwargs):
        del kwargs
        return [
            {
                "game_id": "mlb:746123",
                "team": "NYY",
                "pitcher_id": 543037,
                "pitcher_name": "Gerrit Cole",
                "projected_role": "Closer",
                "availability_score": 0.8,
                "availability_label": "Available",
                "appearance_probability": 0.65,
                "expected_batters_faced_min": 3,
                "expected_batters_faced_max": 5,
                "recent_workload": "Rested",
                "reason": "High leverage",
                "generation": "fixture-v1",
                "batter_pa": 10,
                "batter_hits": 3,
                "batter_home_runs": 1,
                "batter_strikeouts": 4,
            }
        ]

    def get_streaks(self, **kwargs):
        del kwargs
        return [
            {
                "through_date": "2026-07-12",
                "group": "batter",
                "metric": "hit",
                "subject_id": "592450",
                "subject_name": "Aaron Judge",
                "team": "NYY",
                "streak": 8,
                "last_game_date": "2026-07-12",
            }
        ]

    def get_player_leaderboard(self, **kwargs):
        del kwargs
        return [
            {
                "season": 2026,
                "player_id": 592450,
                "name": "Aaron Judge",
                "team": "NYY",
                "games": 80,
                "pa": 350,
                "ab": 300,
                "hits": 96,
                "home_runs": 31,
                "rbi": 70,
                "walks": 45,
                "strikeouts": 82,
                "total_bases": 209,
                "average": 0.32,
                "ops": 1.113,
                "last_game_date": "2026-07-12",
            }
        ]

    def get_team_leaderboard(self, **kwargs):
        del kwargs
        return [
            {
                "season": 2026,
                "team_id": 147,
                "name": "New York Yankees",
                "abbreviation": "NYY",
                "games": 90,
                "pa": 3400,
                "runs": 480,
                "hits": 800,
                "walks": 350,
                "strikeouts": 700,
                "home_runs": 140,
                "innings_outs": 2400,
                "runs_allowed": 390,
                "earned_runs_allowed": 360,
                "hits_allowed": 740,
                "walks_allowed": 270,
                "strikeouts_pitched": 820,
                "home_runs_allowed": 95,
                "average": 0.262,
                "era": 4.05,
                "last_game_date": "2026-07-12",
            }
        ]


class FakeCache:
    def ping(self) -> bool:
        return True

    def get_or_load(self, key, loader, *, ttl_seconds, negative_ttl_seconds):
        del key, ttl_seconds, negative_ttl_seconds
        return CacheLoadResult(loader(), CacheOutcome.MISS)

    def close(self) -> None:
        return None


def research_client() -> TestClient:
    app = create_app(settings(schema_revision="0005_phase7_analytics"))
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


def test_phase7_analytics_contracts_are_bounded_and_typed() -> None:
    paths = [
        "/api/v1/research/batter-vs-pitcher?batter_id=592450&pitcher_id=543037",
        "/api/v1/matchups/pitcher-vs-opponent?pitcher_id=543037&team=NYY",
        "/api/v1/matchups/bullpen?game_id=mlb:746123&batter_id=592450",
        "/api/v1/streaks?group=batter&metric=hit",
        "/api/v1/stats/players?group=batting&sort=home_runs",
        "/api/v1/stats/teams?group=batting&sort=runs",
    ]
    with research_client() as client:
        responses = [client.get(path) for path in paths]

    assert all(response.status_code == 200 for response in responses)
    assert responses[0].json()["data"]["coverage"]["pitch_count"] == 12
    assert responses[2].json()["data"][0]["appearance_probability"] == 0.65
    assert responses[3].json()["data"][0]["streak"] == 8
    assert responses[4].json()["data"][0]["home_runs"] == 31
    assert responses[5].json()["data"][0]["runs"] == 480
