"""Read-only repository contracts shared by API and worker delivery layers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


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


@dataclass(frozen=True, slots=True)
class PlayerRecord:
    player_id: str
    name: str | None
    active_status: str
    player_type: str
    latest_season: int | None = None
    last_game_date: str | None = None


@dataclass(frozen=True, slots=True)
class BattingSummaryRecord:
    season: int
    games: int
    pa: int
    ab: int
    hits: int
    doubles: int
    triples: int
    walks: int
    hit_by_pitch: int
    strikeouts: int
    home_runs: int
    rbi: int
    total_bases: int
    batting_average: float | None = None
    on_base_percentage: float | None = None
    slugging_percentage: float | None = None


@dataclass(frozen=True, slots=True)
class PitchingSummaryRecord:
    season: int
    games: int
    starts: int
    innings_outs: int
    pitch_count: int
    batters_faced: int
    hits: int
    walks: int
    hit_by_pitch: int
    strikeouts: int
    home_runs: int
    runs: int
    earned_runs: int
    earned_run_average: float | None = None
    whip: float | None = None


@dataclass(frozen=True, slots=True)
class PlayerGameLogRecord:
    game_id: str
    game_date: str
    season: int
    group: str
    opponent: str | None = None
    games: int = 1
    pa: int | None = None
    ab: int | None = None
    hits: int | None = None
    walks: int | None = None
    strikeouts: int | None = None
    home_runs: int | None = None
    rbi: int | None = None
    total_bases: int | None = None
    is_starter: bool | None = None
    innings_outs: int | None = None
    pitch_count: int | None = None
    batters_faced: int | None = None
    runs: int | None = None
    earned_runs: int | None = None


@dataclass(frozen=True, slots=True)
class BatterPitcherMatchupRecord:
    batter_id: str
    batter_name: str | None
    pitcher_id: str
    pitcher_name: str | None
    season: int | None
    games: int
    pa: int
    ab: int
    hits: int
    doubles: int
    triples: int
    walks: int
    hit_by_pitch: int
    strikeouts: int
    home_runs: int
    rbi: int
    total_bases: int
    batting_average: float | None = None
    on_base_percentage: float | None = None
    slugging_percentage: float | None = None
    last_game_date: str | None = None


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


class ResearchRepository(Protocol):
    """Bounded player and matchup reads from persisted facts and summaries."""

    def get_data_version(self) -> str: ...

    def get_players(
        self,
        *,
        query: str | None,
        role: str | None,
        season: int | None,
        limit: int,
        cursor: str | None,
    ) -> list[PlayerRecord]: ...

    def get_player(self, player_id: str) -> PlayerRecord | None: ...

    def get_player_batting_summary(
        self, player_id: str, *, season: int | None
    ) -> BattingSummaryRecord | None: ...

    def get_player_pitching_summary(
        self, player_id: str, *, season: int | None
    ) -> PitchingSummaryRecord | None: ...

    def get_player_game_logs(
        self,
        player_id: str,
        *,
        season: int | None,
        group: str,
        limit: int,
    ) -> list[PlayerGameLogRecord]: ...

    def get_batter_pitcher_matchup(
        self,
        *,
        batter_id: str,
        pitcher_id: str,
        season: int | None,
    ) -> BatterPitcherMatchupRecord | None: ...

    def get_batter_pitcher_logs(
        self,
        *,
        batter_id: str,
        pitcher_id: str,
        season: int | None,
        limit: int,
    ) -> list[PlayerGameLogRecord]: ...

    def get_advanced_matchup(
        self, *, batter_id: str, pitcher_id: str, season: int | None, limit: int
    ) -> dict[str, Any]: ...

    def get_pitcher_opponent(
        self, *, pitcher_id: str, team: str | None, season: int | None, limit: int
    ) -> dict[str, Any]: ...

    def get_bullpen_projection(
        self, *, game_id: str, team: str | None, batter_id: str | None
    ) -> list[dict[str, Any]]: ...

    def get_streaks(
        self, *, through_date: str | None, group: str, metric: str, limit: int
    ) -> list[dict[str, Any]]: ...

    def get_player_leaderboard(
        self, *, season: int | None, group: str, sort: str, query: str | None, limit: int
    ) -> list[dict[str, Any]]: ...

    def get_team_leaderboard(
        self, *, season: int | None, group: str, sort: str, limit: int
    ) -> list[dict[str, Any]]: ...


class ApplicationRepository(OperationsRepository, SlateRepository, ResearchRepository, Protocol):
    """Combined read boundary shared by API services and one connection pool."""
