"""PostgreSQL operational reads used by the FastAPI production shell."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Engine

from all_rise.repositories.protocols import (
    DataSourceStatusRecord,
    GameRecord,
    GameWeatherRecord,
    RepositoryReadiness,
)


class PostgresOperationsRepository:
    def __init__(
        self,
        database_url: str,
        *,
        pool_size: int = 5,
        max_overflow: int = 5,
    ) -> None:
        self._engine: Engine = create_engine(
            database_url,
            pool_pre_ping=True,
            pool_size=pool_size,
            max_overflow=max_overflow,
        )

    def check_readiness(self) -> RepositoryReadiness:
        try:
            with self._engine.connect() as connection:
                connection.execute(text("SELECT 1"))
                revision = connection.execute(
                    text("SELECT version_num FROM alembic_version LIMIT 1")
                ).scalar_one_or_none()
            return RepositoryReadiness(True, str(revision) if revision else None)
        except Exception as exc:
            return RepositoryReadiness(False, None, type(exc).__name__)

    def get_data_status(self, *, limit: int) -> list[DataSourceStatusRecord]:
        if not inspect(self._engine).has_table("data_source_status"):
            return []
        statement = text(
            """
            SELECT source, watermark, freshness_status,
                   last_success_at, last_failure_at, detail
            FROM data_source_status
            ORDER BY source
            LIMIT :limit
            """
        )
        with self._engine.connect() as connection:
            rows = connection.execute(statement, {"limit": limit}).mappings()
            return [
                DataSourceStatusRecord(
                    source=str(row["source"]),
                    watermark=str(row["watermark"]) if row["watermark"] else None,
                    freshness_status=str(row["freshness_status"]),
                    last_success_at=(
                        str(row["last_success_at"]) if row["last_success_at"] else None
                    ),
                    last_failure_at=(
                        str(row["last_failure_at"]) if row["last_failure_at"] else None
                    ),
                    detail=str(row["detail"]) if row["detail"] else None,
                )
                for row in rows
            ]

    def get_data_version(self) -> str:
        if not inspect(self._engine).has_table("data_source_status"):
            return "empty"
        statement = text(
            """
            SELECT COALESCE(
                string_agg(source || ':' || COALESCE(watermark, ''), ',' ORDER BY source),
                'empty'
            )
            FROM data_source_status
            """
        )
        with self._engine.connect() as connection:
            return str(connection.execute(statement).scalar_one())

    def get_games(
        self,
        *,
        game_date: str,
        team: str | None,
        status: str | None,
        limit: int,
        cursor: str | None,
    ) -> list[GameRecord]:
        conditions = ["g.game_date = :game_date"]
        params: dict[str, object] = {"game_date": game_date, "limit": limit}
        if team:
            conditions.append(
                "(upper(away.abbreviation) = :team OR upper(home.abbreviation) = :team)"
            )
            params["team"] = team.upper()
        if status:
            conditions.append("lower(g.game_status) = :status")
            params["status"] = status.lower()
        if cursor:
            conditions.append("g.source_game_id > :cursor")
            params["cursor"] = cursor
        statement = text(
            f"""
            {_GAME_SELECT}
            WHERE {' AND '.join(conditions)}
            ORDER BY g.source_game_id
            LIMIT :limit
            """
        )
        with self._engine.connect() as connection:
            rows = connection.execute(statement, params).mappings()
            return [_game_record(row) for row in rows]

    def get_game(self, game_id: str) -> GameRecord | None:
        statement = text(f"{_GAME_SELECT} WHERE g.source_game_id = :game_id LIMIT 1")
        with self._engine.connect() as connection:
            row = connection.execute(statement, {"game_id": game_id}).mappings().first()
            return _game_record(row) if row else None

    def get_weather(
        self,
        *,
        game_date: str,
        game_id: str | None,
        limit: int,
    ) -> list[GameWeatherRecord]:
        conditions = ["g.game_date = :game_date"]
        params: dict[str, object] = {"game_date": game_date, "limit": limit}
        if game_id:
            conditions.append("g.source_game_id = :game_id")
            params["game_id"] = game_id
        statement = text(
            f"""
            {_WEATHER_SELECT}
            WHERE {' AND '.join(conditions)}
            ORDER BY g.game_time_utc NULLS LAST, g.source_game_id
            LIMIT :limit
            """
        )
        with self._engine.connect() as connection:
            rows = connection.execute(statement, params).mappings()
            return [_weather_record(row) for row in rows]

    def get_game_weather(self, game_id: str) -> GameWeatherRecord | None:
        statement = text(
            f"{_WEATHER_SELECT} WHERE g.source_game_id = :game_id LIMIT 1"
        )
        with self._engine.connect() as connection:
            row = connection.execute(statement, {"game_id": game_id}).mappings().first()
            return _weather_record(row) if row else None

    def close(self) -> None:
        self._engine.dispose()


_GAME_SELECT = """
    SELECT g.source_game_id AS game_id, g.game_date, g.season,
           g.game_time_utc, g.game_status AS status,
           away.name AS away_team, away.abbreviation AS away_team_abbreviation,
           home.name AS home_team, home.abbreviation AS home_team_abbreviation,
           g.away_score, g.home_score,
           CAST(away_pitcher.provider_player_id AS TEXT) AS away_probable_pitcher_id,
           away_pitcher.name AS away_probable_pitcher,
           CAST(home_pitcher.provider_player_id AS TEXT) AS home_probable_pitcher_id,
           home_pitcher.name AS home_probable_pitcher,
           venue.name AS venue_name, venue.city AS venue_city, venue.roof_type,
           g.source_updated_at
    FROM games g
    JOIN teams away ON away.id = g.away_team_id
    JOIN teams home ON home.id = g.home_team_id
    LEFT JOIN players away_pitcher ON away_pitcher.id = g.away_probable_pitcher_id
    LEFT JOIN players home_pitcher ON home_pitcher.id = g.home_probable_pitcher_id
    LEFT JOIN venues venue ON venue.id = g.venue_id
"""

_WEATHER_SELECT = """
    SELECT g.source_game_id AS game_id, g.game_date, g.game_time_utc,
           g.game_status AS status,
           away.name AS away_team, away.abbreviation AS away_team_abbreviation,
           home.name AS home_team, home.abbreviation AS home_team_abbreviation,
           venue.name AS venue_name, venue.roof_type,
           weather.observed_at, weather.forecast_for, weather.source,
           weather.condition, weather.temperature_f, weather.feels_like_f,
           weather.humidity_percent, weather.wind_speed_mph,
           weather.wind_direction_degrees, weather.wind_out_mph,
           weather.precipitation_probability, weather.hitter_adjustment,
           weather.pitcher_adjustment, weather.edge_label, weather.stale
    FROM games g
    JOIN teams away ON away.id = g.away_team_id
    JOIN teams home ON home.id = g.home_team_id
    LEFT JOIN venues venue ON venue.id = g.venue_id
    LEFT JOIN LATERAL (
        SELECT ws.* FROM weather_snapshots ws
        WHERE ws.game_id = g.id
        ORDER BY ws.observed_at DESC
        LIMIT 1
    ) weather ON TRUE
"""


def _text_value(value: object | None) -> str | None:
    return str(value) if value is not None else None


def _float_value(value: object | None) -> float | None:
    return float(value) if value is not None else None


def _game_record(row: Mapping[str, Any]) -> GameRecord:
    values = row
    return GameRecord(
        game_id=str(values["game_id"]),
        game_date=str(values["game_date"]),
        season=int(values["season"]),
        game_time_utc=_text_value(values["game_time_utc"]),
        status=_text_value(values["status"]),
        away_team=str(values["away_team"]),
        away_team_abbreviation=_text_value(values["away_team_abbreviation"]),
        home_team=str(values["home_team"]),
        home_team_abbreviation=_text_value(values["home_team_abbreviation"]),
        away_score=int(values["away_score"]) if values["away_score"] is not None else None,
        home_score=int(values["home_score"]) if values["home_score"] is not None else None,
        away_probable_pitcher_id=_text_value(values["away_probable_pitcher_id"]),
        away_probable_pitcher=_text_value(values["away_probable_pitcher"]),
        home_probable_pitcher_id=_text_value(values["home_probable_pitcher_id"]),
        home_probable_pitcher=_text_value(values["home_probable_pitcher"]),
        venue_name=_text_value(values["venue_name"]),
        venue_city=_text_value(values["venue_city"]),
        roof_type=_text_value(values["roof_type"]),
        source_updated_at=_text_value(values["source_updated_at"]),
    )


def _weather_record(row: Mapping[str, Any]) -> GameWeatherRecord:
    values = row
    return GameWeatherRecord(
        game_id=str(values["game_id"]),
        game_date=str(values["game_date"]),
        game_time_utc=_text_value(values["game_time_utc"]),
        status=_text_value(values["status"]),
        away_team=str(values["away_team"]),
        away_team_abbreviation=_text_value(values["away_team_abbreviation"]),
        home_team=str(values["home_team"]),
        home_team_abbreviation=_text_value(values["home_team_abbreviation"]),
        venue_name=_text_value(values["venue_name"]),
        roof_type=_text_value(values["roof_type"]),
        observed_at=_text_value(values["observed_at"]),
        forecast_for=_text_value(values["forecast_for"]),
        source=_text_value(values["source"]),
        condition=_text_value(values["condition"]),
        temperature_f=_float_value(values["temperature_f"]),
        feels_like_f=_float_value(values["feels_like_f"]),
        humidity_percent=_float_value(values["humidity_percent"]),
        wind_speed_mph=_float_value(values["wind_speed_mph"]),
        wind_direction_degrees=_float_value(values["wind_direction_degrees"]),
        wind_out_mph=_float_value(values["wind_out_mph"]),
        precipitation_probability=_float_value(values["precipitation_probability"]),
        hitter_adjustment=_float_value(values["hitter_adjustment"]),
        pitcher_adjustment=_float_value(values["pitcher_adjustment"]),
        edge_label=_text_value(values["edge_label"]),
        stale=bool(values["stale"]) if values["stale"] is not None else False,
    )
