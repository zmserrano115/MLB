"""Read-only repository contracts shared by API and worker delivery layers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class RepositoryReadiness:
    reachable: bool
    schema_revision: str | None
    detail: str | None = None


@dataclass(frozen=True, slots=True)
class DataSourceStatusRecord:
    source: str
    watermark: str | None
    freshness_status: str
    last_success_at: str | None = None
    last_failure_at: str | None = None
    detail: str | None = None


@dataclass(frozen=True, slots=True)
class GameRecord:
    game_id: str
    game_date: str
    season: int
    game_time_utc: str | None
    status: str | None
    away_team: str
    away_team_abbreviation: str | None
    home_team: str
    home_team_abbreviation: str | None
    away_score: int | None = None
    home_score: int | None = None
    away_probable_pitcher_id: str | None = None
    away_probable_pitcher: str | None = None
    home_probable_pitcher_id: str | None = None
    home_probable_pitcher: str | None = None
    venue_name: str | None = None
    venue_city: str | None = None
    roof_type: str | None = None
    source_updated_at: str | None = None


@dataclass(frozen=True, slots=True)
class GameWeatherRecord:
    game_id: str
    game_date: str
    game_time_utc: str | None
    status: str | None
    away_team: str
    away_team_abbreviation: str | None
    home_team: str
    home_team_abbreviation: str | None
    venue_name: str | None = None
    roof_type: str | None = None
    observed_at: str | None = None
    forecast_for: str | None = None
    source: str | None = None
    condition: str | None = None
    temperature_f: float | None = None
    feels_like_f: float | None = None
    humidity_percent: float | None = None
    wind_speed_mph: float | None = None
    wind_direction_degrees: float | None = None
    wind_out_mph: float | None = None
    precipitation_probability: float | None = None
    hitter_adjustment: float | None = None
    pitcher_adjustment: float | None = None
    edge_label: str | None = None
    stale: bool = False


class OperationsRepository(Protocol):
    """Bounded operational reads; implementations must never mutate data."""

    def check_readiness(self) -> RepositoryReadiness: ...

    def get_data_version(self) -> str: ...

    def get_data_status(self, *, limit: int) -> list[DataSourceStatusRecord]: ...

    def close(self) -> None: ...


class SlateRepository(Protocol):
    """Read-only schedule and weather snapshots; never call providers inline."""

    def get_data_version(self) -> str: ...

    def get_games(
        self,
        *,
        game_date: str,
        team: str | None,
        status: str | None,
        limit: int,
        cursor: str | None,
    ) -> list[GameRecord]: ...

    def get_game(self, game_id: str) -> GameRecord | None: ...

    def get_weather(
        self,
        *,
        game_date: str,
        game_id: str | None,
        limit: int,
    ) -> list[GameWeatherRecord]: ...

    def get_game_weather(self, game_id: str) -> GameWeatherRecord | None: ...


class ApplicationRepository(OperationsRepository, SlateRepository, Protocol):
    """Combined read boundary shared by API services and one connection pool."""
