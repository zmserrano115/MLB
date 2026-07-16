from __future__ import annotations

from all_rise.application.slate import SlateService
from all_rise.cache.versioned import CacheLoadResult, CacheOutcome
from all_rise.repositories.protocols import GameRecord, GameWeatherRecord
from all_rise_api.dependencies import get_slate_service
from all_rise_api.main import create_app
from fastapi.testclient import TestClient

from test_phase3_api import settings


class FakeSlateRepository:
    def __init__(self) -> None:
        self.game = GameRecord(
            game_id="mlb:746123",
            game_date="2026-07-13",
            season=2026,
            game_time_utc="2026-07-13T23:05:00+00:00",
            status="Preview",
            away_team="New York Yankees",
            away_team_abbreviation="NYY",
            home_team="Colorado Rockies",
            home_team_abbreviation="COL",
            away_probable_pitcher_id="543037",
            away_probable_pitcher="Gerrit Cole",
            venue_name="Coors Field",
            venue_city="Denver",
            roof_type="Open",
            source_updated_at="2026-07-13T18:00:00+00:00",
        )
        self.weather = GameWeatherRecord(
            game_id=self.game.game_id,
            game_date=self.game.game_date,
            game_time_utc=self.game.game_time_utc,
            status=self.game.status,
            away_team=self.game.away_team,
            away_team_abbreviation=self.game.away_team_abbreviation,
            home_team=self.game.home_team,
            home_team_abbreviation=self.game.home_team_abbreviation,
            venue_name=self.game.venue_name,
            roof_type=self.game.roof_type,
            observed_at="2026-07-13T18:00:00+00:00",
            forecast_for=self.game.game_time_utc,
            source="Open-Meteo",
            condition="Clear",
            temperature_f=84.0,
            wind_speed_mph=9.0,
            wind_out_mph=5.5,
            precipitation_probability=4.0,
            hitter_adjustment=2.1,
            pitcher_adjustment=-0.4,
            edge_label="Hitter boost",
        )

    def get_data_version(self) -> str:
        return "mlb-schedule:2026-07-13,open-meteo:2026-07-13T18:00:00Z"

    def get_games(self, **kwargs) -> list[GameRecord]:
        del kwargs
        return [self.game]

    def get_game(self, game_id: str) -> GameRecord | None:
        return self.game if game_id == self.game.game_id else None

    def get_weather(self, **kwargs) -> list[GameWeatherRecord]:
        del kwargs
        return [self.weather]

    def get_game_weather(self, game_id: str) -> GameWeatherRecord | None:
        return self.weather if game_id == self.weather.game_id else None


class FakeCache:
    def ping(self) -> bool:
        return True

    def get_or_load(self, key, loader, *, ttl_seconds, negative_ttl_seconds):
        del key, ttl_seconds, negative_ttl_seconds
        return CacheLoadResult(loader(), CacheOutcome.MISS)

    def close(self) -> None:
        return None


def slate_client() -> TestClient:
    app = create_app(settings(schema_revision="0004_slate_weather_read_models"))
    service = SlateService(FakeSlateRepository(), FakeCache())
    app.dependency_overrides[get_slate_service] = lambda: service
    return TestClient(app)


def test_games_contract_uses_string_ids_pagination_and_conditional_get() -> None:
    with slate_client() as client:
        response = client.get("/api/v1/games?date=2026-07-13&limit=1")
        conditional = client.get(
            "/api/v1/games?date=2026-07-13&limit=1",
            headers={"if-none-match": response.headers["etag"]},
        )

    assert response.status_code == 200
    assert response.json()["data"][0]["game_id"] == "mlb:746123"
    assert response.json()["data"][0]["away_team"]["abbreviation"] == "NYY"
    assert response.json()["meta"]["pagination"]["limit"] == 1
    assert response.headers["x-cache-status"] == "miss"
    assert conditional.status_code == 304
    assert conditional.content == b""


def test_game_detail_and_safe_not_found_contract() -> None:
    with slate_client() as client:
        detail = client.get("/api/v1/games/mlb:746123")
        missing = client.get("/api/v1/games/mlb:999999")

    assert detail.status_code == 200
    assert detail.json()["data"]["venue"]["name"] == "Coors Field"
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "game_not_found"


def test_weather_contract_serves_only_persisted_snapshot_fields() -> None:
    with slate_client() as client:
        response = client.get("/api/v1/weather?date=2026-07-13")
        detail = client.get("/api/v1/games/mlb:746123/weather")

    weather = response.json()["data"][0]
    assert response.status_code == 200
    assert weather["available"] is True
    assert weather["source"] == "Open-Meteo"
    assert weather["hitter_adjustment"] == 2.1
    assert detail.json()["data"]["forecast_for"] == "2026-07-13T23:05:00Z"


def test_slate_query_bounds_reject_invalid_input() -> None:
    with slate_client() as client:
        bad_date = client.get("/api/v1/games?date=not-a-date")
        bad_team = client.get("/api/v1/games?date=2026-07-13&team=<script>")
        bad_limit = client.get("/api/v1/weather?date=2026-07-13&limit=101")

    assert bad_date.status_code == 422
    assert bad_team.status_code == 422
    assert bad_limit.status_code == 422
    assert bad_limit.json()["error"]["code"] == "validation_error"
