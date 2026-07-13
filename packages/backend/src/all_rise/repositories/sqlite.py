"""Development-only, read-only adapter for the legacy SQLite database."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from urllib.parse import unquote, urlparse

from all_rise.repositories.protocols import (
    DataSourceStatusRecord,
    GameRecord,
    GameWeatherRecord,
    RepositoryReadiness,
)


class SQLiteOperationsRepository:
    def __init__(self, database_url: str) -> None:
        parsed = urlparse(database_url)
        if parsed.scheme != "sqlite":
            raise ValueError("SQLite adapter requires a sqlite:// URL")
        raw_path = unquote(parsed.path)
        if raw_path.startswith("/") and len(raw_path) > 2 and raw_path[2] == ":":
            raw_path = raw_path[1:]
        self._path = Path(raw_path).resolve()

    def _connect(self) -> sqlite3.Connection:
        if not self._path.is_file():
            raise FileNotFoundError(self._path)
        connection = sqlite3.connect(f"file:{self._path.as_posix()}?mode=ro", uri=True)
        connection.row_factory = sqlite3.Row
        return connection

    def check_readiness(self) -> RepositoryReadiness:
        try:
            with self._connect() as connection:
                revision = connection.execute("PRAGMA user_version").fetchone()[0]
                connection.execute("SELECT 1").fetchone()
            return RepositoryReadiness(True, f"sqlite-user-version-{revision}")
        except Exception as exc:
            return RepositoryReadiness(False, None, type(exc).__name__)

    def get_data_status(self, *, limit: int) -> list[DataSourceStatusRecord]:
        del limit
        with self._connect() as connection:
            exists = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='refresh_log'"
            ).fetchone()
            if not exists:
                return []
            columns = {
                row["name"]
                for row in connection.execute("PRAGMA table_info(refresh_log)").fetchall()
            }
            timestamp_column = next(
                (
                    name
                    for name in (
                        "completed_at",
                        "finished_at",
                        "created_at",
                        "started_at",
                        "refresh_date",
                        "timestamp",
                    )
                    if name in columns
                ),
                None,
            )
            watermark = None
            if timestamp_column:
                watermark = connection.execute(
                    f'SELECT MAX("{timestamp_column}") FROM refresh_log'
                ).fetchone()[0]
        return [
            DataSourceStatusRecord(
                source="legacy-sqlite",
                watermark=str(watermark) if watermark else None,
                freshness_status="unknown",
                detail="Development-only compatibility adapter",
            )
        ]

    def get_data_version(self) -> str:
        records = self.get_data_status(limit=1)
        if not records:
            return "empty"
        return f"{records[0].source}:{records[0].watermark or ''}"

    def get_games(
        self,
        *,
        game_date: str,
        team: str | None,
        status: str | None,
        limit: int,
        cursor: str | None,
    ) -> list[GameRecord]:
        with self._connect() as connection:
            columns = self._game_columns(connection)
            identity = (
                "COALESCE(game_id, 'mlb:' || game_pk)"
                if "game_id" in columns
                else "'mlb:' || game_pk"
            )
            filters = ["game_date = ?", f"(? IS NULL OR {identity} > ?)"]
            params: list[object] = [game_date, cursor, cursor]
            if team:
                filters.append("(upper(away_team) = ? OR upper(home_team) = ?)")
                params.extend([team.upper(), team.upper()])
            if status:
                filters.append("lower(game_status) = ?")
                params.append(status.lower())
            params.append(limit)
            rows = connection.execute(
                f"SELECT * FROM games WHERE {' AND '.join(filters)} ORDER BY {identity} LIMIT ?",
                params,
            ).fetchall()
            return [self._sqlite_game_record(row, columns) for row in rows]

    def get_game(self, game_id: str) -> GameRecord | None:
        with self._connect() as connection:
            columns = self._game_columns(connection)
            identity = (
                "COALESCE(game_id, 'mlb:' || game_pk)"
                if "game_id" in columns
                else "'mlb:' || game_pk"
            )
            row = connection.execute(
                f"SELECT * FROM games WHERE {identity} = ? LIMIT 1", (game_id,)
            ).fetchone()
            return self._sqlite_game_record(row, columns) if row else None

    def get_weather(
        self,
        *,
        game_date: str,
        game_id: str | None,
        limit: int,
    ) -> list[GameWeatherRecord]:
        records = self.get_games(
            game_date=game_date,
            team=None,
            status=None,
            limit=limit,
            cursor=None,
        )
        if game_id:
            records = [record for record in records if record.game_id == game_id]
        return [self._empty_weather(record) for record in records]

    def get_game_weather(self, game_id: str) -> GameWeatherRecord | None:
        record = self.get_game(game_id)
        return self._empty_weather(record) if record else None

    @staticmethod
    def _game_columns(connection: sqlite3.Connection) -> set[str]:
        return {row["name"] for row in connection.execute("PRAGMA table_info(games)")}

    @staticmethod
    def _sqlite_game_record(row: sqlite3.Row, columns: set[str]) -> GameRecord:
        def value(name: str):
            return row[name] if name in columns else None

        game_id = value("game_id") or f"mlb:{row['game_pk']}"
        return GameRecord(
            game_id=str(game_id),
            game_date=str(row["game_date"]),
            season=int(row["season"]),
            game_time_utc=str(value("game_time_utc")) if value("game_time_utc") else None,
            status=str(value("game_status")) if value("game_status") else None,
            away_team=str(value("away_team") or "Away team"),
            away_team_abbreviation=str(value("away_team") or "AWAY"),
            home_team=str(value("home_team") or "Home team"),
            home_team_abbreviation=str(value("home_team") or "HOME"),
            away_score=int(value("away_score")) if value("away_score") is not None else None,
            home_score=int(value("home_score")) if value("home_score") is not None else None,
            away_probable_pitcher_id=(
                str(value("away_probable_pitcher_id"))
                if value("away_probable_pitcher_id") is not None
                else None
            ),
            away_probable_pitcher=(
                str(value("away_probable_pitcher")) if value("away_probable_pitcher") else None
            ),
            home_probable_pitcher_id=(
                str(value("home_probable_pitcher_id"))
                if value("home_probable_pitcher_id") is not None
                else None
            ),
            home_probable_pitcher=(
                str(value("home_probable_pitcher")) if value("home_probable_pitcher") else None
            ),
            venue_name=str(value("venue_name")) if value("venue_name") else None,
            venue_city=str(value("venue_city")) if value("venue_city") else None,
            roof_type=str(value("roof_type")) if value("roof_type") else None,
            source_updated_at=str(value("updated_at")) if value("updated_at") else None,
        )

    @staticmethod
    def _empty_weather(record: GameRecord) -> GameWeatherRecord:
        return GameWeatherRecord(
            game_id=record.game_id,
            game_date=record.game_date,
            game_time_utc=record.game_time_utc,
            status=record.status,
            away_team=record.away_team,
            away_team_abbreviation=record.away_team_abbreviation,
            home_team=record.home_team,
            home_team_abbreviation=record.home_team_abbreviation,
            venue_name=record.venue_name,
            roof_type=record.roof_type,
        )

    def close(self) -> None:
        return None
