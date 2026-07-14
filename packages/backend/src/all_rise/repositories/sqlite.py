"""Development-only, read-only adapter for the legacy SQLite database."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from all_rise.repositories.protocols import (
    BatterPitcherMatchupRecord,
    BattingSummaryRecord,
    DataSourceStatusRecord,
    GameRecord,
    GameWeatherRecord,
    PitchingSummaryRecord,
    PlayerGameLogRecord,
    PlayerRecord,
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

    def get_players(
        self,
        *,
        query: str | None,
        role: str | None,
        season: int | None,
        limit: int,
        cursor: str | None,
    ) -> list[PlayerRecord]:
        conditions = ["player_name IS NOT NULL"]
        params: list[object] = []
        if query:
            conditions.append("player_name LIKE ? COLLATE NOCASE")
            params.append(f"%{query}%")
        if cursor:
            conditions.append("player_id > ?")
            params.append(int(cursor))
        batter_exists = (
            "EXISTS (SELECT 1 FROM batter_pitcher_game_logs b WHERE b.batter_id=p.player_id"
        )
        pitcher_exists = (
            "EXISTS (SELECT 1 FROM pitcher_game_logs pg WHERE pg.pitcher_id=p.player_id"
        )
        if season:
            batter_exists += " AND b.season = ?"
            pitcher_exists += " AND pg.season = ?"
        batter_exists += ")"
        pitcher_exists += ")"
        role_condition = None
        if role == "batter":
            role_condition = batter_exists
            if season:
                params.append(season)
        elif role == "pitcher":
            role_condition = pitcher_exists
            if season:
                params.append(season)
        elif role == "two-way":
            role_condition = f"({batter_exists} AND {pitcher_exists})"
            if season:
                params.extend([season, season])
        elif season:
            role_condition = f"({batter_exists} OR {pitcher_exists})"
            params.extend([season, season])
        if role_condition:
            conditions.append(role_condition)
        params.append(limit)
        statement = f"""
            SELECT p.player_id, p.player_name, p.active_status,
                   CASE
                     WHEN EXISTS (
                       SELECT 1 FROM batter_pitcher_game_logs b
                       WHERE b.batter_id=p.player_id
                     ) AND EXISTS (
                       SELECT 1 FROM pitcher_game_logs pg
                       WHERE pg.pitcher_id=p.player_id
                     )
                       THEN 'two-way'
                     WHEN EXISTS (
                       SELECT 1 FROM pitcher_game_logs pg
                       WHERE pg.pitcher_id=p.player_id
                     )
                       THEN 'pitcher'
                     WHEN EXISTS (
                       SELECT 1 FROM batter_pitcher_game_logs b
                       WHERE b.batter_id=p.player_id
                     )
                       THEN 'batter'
                     ELSE 'unknown'
                   END AS player_type,
                   MAX(
                     COALESCE((
                       SELECT MAX(b.season) FROM batter_pitcher_game_logs b
                       WHERE b.batter_id=p.player_id
                     ), 0),
                     COALESCE((
                       SELECT MAX(pg.season) FROM pitcher_game_logs pg
                       WHERE pg.pitcher_id=p.player_id
                     ), 0)
                   ) AS latest_season,
                   MAX(
                     COALESCE((
                       SELECT MAX(b.game_date) FROM batter_pitcher_game_logs b
                       WHERE b.batter_id=p.player_id
                     ), ''),
                     COALESCE((
                       SELECT MAX(pg.game_date) FROM pitcher_game_logs pg
                       WHERE pg.pitcher_id=p.player_id
                     ), '')
                   ) AS last_game_date
            FROM players p WHERE {" AND ".join(conditions)}
            ORDER BY p.player_id LIMIT ?
        """
        with self._connect() as connection:
            rows = connection.execute(statement, params).fetchall()
            return [self._player_record(row) for row in rows]

    def get_player(self, player_id: str) -> PlayerRecord | None:
        records = self.get_players(
            query=None, role=None, season=None, limit=1, cursor=str(int(player_id) - 1)
        )
        return records[0] if records and records[0].player_id == player_id else None

    def get_player_batting_summary(
        self, player_id: str, *, season: int | None
    ) -> BattingSummaryRecord | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT season, COUNT(DISTINCT game_pk) AS games,
                       SUM(PA) AS pa, SUM(AB) AS ab, SUM(H) AS hits,
                       SUM(doubles) AS doubles, SUM(triples) AS triples,
                       SUM(BB) AS walks, SUM(HBP) AS hit_by_pitch,
                       SUM(SO) AS strikeouts, SUM(HR) AS home_runs,
                       SUM(RBI) AS rbi, SUM(TB) AS total_bases
                FROM batter_pitcher_game_logs
                WHERE batter_id=? AND season=COALESCE(?, (
                    SELECT MAX(latest.season) FROM batter_pitcher_game_logs latest
                    WHERE latest.batter_id=?
                ))
                GROUP BY season
                HAVING COUNT(*) > 0
                """,
                (int(player_id), season, int(player_id)),
            ).fetchone()
        return self._batting_summary(row) if row else None

    def get_player_pitching_summary(
        self, player_id: str, *, season: int | None
    ) -> PitchingSummaryRecord | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM pitcher_stats WHERE pitcher_id=?
                  AND (? IS NULL OR season=?) ORDER BY season DESC LIMIT 1
                """,
                (int(player_id), season, season),
            ).fetchone()
        return self._pitching_summary(row) if row else None

    def get_player_game_logs(
        self,
        player_id: str,
        *,
        season: int | None,
        group: str,
        limit: int,
    ) -> list[PlayerGameLogRecord]:
        if group == "pitching":
            statement = """
                SELECT COALESCE(game_id, 'mlb:' || game_pk) AS game_id,
                       game_date, season, opponent, is_starter, IP_outs AS innings_outs,
                       pitch_count, BF AS batters_faced, H AS hits, BB AS walks,
                       SO AS strikeouts, HR AS home_runs, R AS runs, ER AS earned_runs
                FROM pitcher_game_logs WHERE pitcher_id=?
                  AND (? IS NULL OR season=?)
                ORDER BY game_date DESC, game_pk DESC LIMIT ?
            """
        else:
            statement = """
                SELECT COALESCE(game_id, 'mlb:' || game_pk) AS game_id,
                       game_date, season, pitching_team AS opponent,
                       SUM(PA) AS pa, SUM(AB) AS ab, SUM(H) AS hits,
                       SUM(BB) AS walks, SUM(SO) AS strikeouts,
                       SUM(HR) AS home_runs, SUM(RBI) AS rbi, SUM(TB) AS total_bases
                FROM batter_pitcher_game_logs WHERE batter_id=?
                  AND (? IS NULL OR season=?)
                GROUP BY game_pk, game_id, game_date, season, pitching_team
                ORDER BY game_date DESC, game_pk DESC LIMIT ?
            """
        with self._connect() as connection:
            rows = connection.execute(statement, (int(player_id), season, season, limit)).fetchall()
            return [self._player_game_log(row, group) for row in rows]

    def get_batter_pitcher_matchup(
        self,
        *,
        batter_id: str,
        pitcher_id: str,
        season: int | None,
    ) -> BatterPitcherMatchupRecord | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT batter.player_id AS batter_id, batter.player_name AS batter_name,
                       pitcher.player_id AS pitcher_id, pitcher.player_name AS pitcher_name,
                       ? AS season, COUNT(DISTINCT b.game_pk) AS games,
                       SUM(b.PA) AS pa, SUM(b.AB) AS ab, SUM(b.H) AS hits,
                       SUM(b.doubles) AS doubles, SUM(b.triples) AS triples,
                       SUM(b.BB) AS walks, SUM(b.HBP) AS hit_by_pitch,
                       SUM(b.SO) AS strikeouts, SUM(b.HR) AS home_runs,
                       SUM(b.RBI) AS rbi, SUM(b.TB) AS total_bases,
                       MAX(b.game_date) AS last_game_date
                FROM batter_pitcher_game_logs b
                JOIN players batter ON batter.player_id=b.batter_id
                JOIN players pitcher ON pitcher.player_id=b.pitcher_id
                WHERE b.batter_id=? AND b.pitcher_id=?
                  AND (? IS NULL OR b.season=?)
                GROUP BY batter.player_id, batter.player_name,
                         pitcher.player_id, pitcher.player_name
                """,
                (season, int(batter_id), int(pitcher_id), season, season),
            ).fetchone()
        return self._matchup_record(row) if row else None

    def get_batter_pitcher_logs(
        self,
        *,
        batter_id: str,
        pitcher_id: str,
        season: int | None,
        limit: int,
    ) -> list[PlayerGameLogRecord]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT COALESCE(game_id, 'mlb:' || game_pk) AS game_id,
                       game_date, season, pitching_team AS opponent,
                       PA AS pa, AB AS ab, H AS hits, BB AS walks,
                       SO AS strikeouts, HR AS home_runs, RBI AS rbi, TB AS total_bases
                FROM batter_pitcher_game_logs
                WHERE batter_id=? AND pitcher_id=?
                  AND (? IS NULL OR season=?)
                ORDER BY game_date DESC, game_pk DESC LIMIT ?
                """,
                (int(batter_id), int(pitcher_id), season, season, limit),
            ).fetchall()
            return [self._player_game_log(row, "batting") for row in rows]

    def get_advanced_matchup(
        self,
        *,
        batter_id: str,
        pitcher_id: str,
        season: int | None,
        limit: int,
    ) -> dict[str, Any]:
        del limit
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT COUNT(*) pitch_count, COUNT(DISTINCT game_pk) games,
                       MAX(game_date) last_game_date
                FROM pitch_level_events WHERE batter_id=? AND pitcher_id=?
                  AND (? IS NULL OR season=?)
                """,
                (int(batter_id), int(pitcher_id), season, season),
            ).fetchone()
        return {
            "coverage": {
                "pitch_count": int(row["pitch_count"] or 0),
                "games": int(row["games"] or 0),
                "last_game_date": str(row["last_game_date"]) if row["last_game_date"] else None,
            },
            "pitch_types": [],
            "sequences": [],
        }

    def get_pitcher_opponent(
        self,
        *,
        pitcher_id: str,
        team: str | None,
        season: int | None,
        limit: int,
    ) -> dict[str, Any]:
        del pitcher_id, team, season, limit
        return {"splits": [], "game_logs": []}

    def get_bullpen_projection(
        self, *, game_id: str, team: str | None, batter_id: str | None
    ) -> list[dict[str, Any]]:
        del game_id, team, batter_id
        return []

    def get_streaks(
        self,
        *,
        through_date: str | None,
        group: str,
        metric: str,
        limit: int,
    ) -> list[dict[str, Any]]:
        del through_date, group, metric, limit
        return []

    def get_player_leaderboard(
        self,
        *,
        season: int | None,
        group: str,
        sort: str,
        query: str | None,
        limit: int,
    ) -> list[dict[str, Any]]:
        del season, group, sort, query, limit
        return []

    def get_team_leaderboard(
        self, *, season: int | None, group: str, sort: str, limit: int
    ) -> list[dict[str, Any]]:
        del season, group, sort, limit
        return []

    @staticmethod
    def _game_columns(connection: sqlite3.Connection) -> set[str]:
        return {row["name"] for row in connection.execute("PRAGMA table_info(games)")}

    @staticmethod
    def _sqlite_game_record(row: sqlite3.Row, columns: set[str]) -> GameRecord:
        def value(name: str) -> Any:
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

    @staticmethod
    def _player_record(row: sqlite3.Row) -> PlayerRecord:
        latest_season = int(row["latest_season"]) if row["latest_season"] else None
        return PlayerRecord(
            player_id=str(row["player_id"]),
            name=str(row["player_name"]) if row["player_name"] else None,
            active_status=str(row["active_status"] or "unknown"),
            player_type=str(row["player_type"]),
            latest_season=latest_season,
            last_game_date=str(row["last_game_date"]) if row["last_game_date"] else None,
        )

    @staticmethod
    def _batting_summary(row: sqlite3.Row) -> BattingSummaryRecord:
        pa, ab, hits = int(row["pa"] or 0), int(row["ab"] or 0), int(row["hits"] or 0)
        walks, hbp = int(row["walks"] or 0), int(row["hit_by_pitch"] or 0)
        total_bases = int(row["total_bases"] or 0)

        def ratio(numerator: int, denominator: int) -> float | None:
            return round(numerator / denominator, 5) if denominator else None

        return BattingSummaryRecord(
            season=int(row["season"]),
            games=int(row["games"]),
            pa=pa,
            ab=ab,
            hits=hits,
            doubles=int(row["doubles"] or 0),
            triples=int(row["triples"] or 0),
            walks=walks,
            hit_by_pitch=hbp,
            strikeouts=int(row["strikeouts"] or 0),
            home_runs=int(row["home_runs"] or 0),
            rbi=int(row["rbi"] or 0),
            total_bases=total_bases,
            batting_average=ratio(hits, ab),
            on_base_percentage=ratio(hits + walks + hbp, pa),
            slugging_percentage=ratio(total_bases, ab),
        )

    @staticmethod
    def _pitching_summary(row: sqlite3.Row) -> PitchingSummaryRecord:
        pitch_count = round(float(row["avg_pitch_count_per_start"] or 0) * int(row["starts"] or 0))
        return PitchingSummaryRecord(
            season=int(row["season"]),
            games=int(row["games"]),
            starts=int(row["starts"]),
            innings_outs=int(row["IP_outs"]),
            pitch_count=pitch_count,
            batters_faced=int(row["BF"]),
            hits=int(row["H"]),
            walks=int(row["BB"]),
            hit_by_pitch=int(row["HBP"]),
            strikeouts=int(row["SO"]),
            home_runs=int(row["HR"]),
            runs=int(row["R"]),
            earned_runs=int(row["ER"]),
            earned_run_average=float(row["ERA"]) if row["ERA"] is not None else None,
            whip=float(row["WHIP"]) if row["WHIP"] is not None else None,
        )

    @staticmethod
    def _player_game_log(row: sqlite3.Row, group: str) -> PlayerGameLogRecord:
        keys = set(row.keys())

        def integer(name: str) -> int | None:
            return int(row[name]) if name in keys and row[name] is not None else None

        return PlayerGameLogRecord(
            game_id=str(row["game_id"]),
            game_date=str(row["game_date"]),
            season=int(row["season"]),
            group=group,
            opponent=str(row["opponent"]) if row["opponent"] else None,
            pa=integer("pa"),
            ab=integer("ab"),
            hits=integer("hits"),
            walks=integer("walks"),
            strikeouts=integer("strikeouts"),
            home_runs=integer("home_runs"),
            rbi=integer("rbi"),
            total_bases=integer("total_bases"),
            is_starter=bool(row["is_starter"]) if "is_starter" in keys else None,
            innings_outs=integer("innings_outs"),
            pitch_count=integer("pitch_count"),
            batters_faced=integer("batters_faced"),
            runs=integer("runs"),
            earned_runs=integer("earned_runs"),
        )

    @staticmethod
    def _matchup_record(row: sqlite3.Row) -> BatterPitcherMatchupRecord:
        summary = SQLiteOperationsRepository._batting_summary(row)
        return BatterPitcherMatchupRecord(
            batter_id=str(row["batter_id"]),
            batter_name=str(row["batter_name"]),
            pitcher_id=str(row["pitcher_id"]),
            pitcher_name=str(row["pitcher_name"]),
            season=int(row["season"]) if row["season"] is not None else None,
            games=summary.games,
            pa=summary.pa,
            ab=summary.ab,
            hits=summary.hits,
            doubles=summary.doubles,
            triples=summary.triples,
            walks=summary.walks,
            hit_by_pitch=summary.hit_by_pitch,
            strikeouts=summary.strikeouts,
            home_runs=summary.home_runs,
            rbi=summary.rbi,
            total_bases=summary.total_bases,
            batting_average=summary.batting_average,
            on_base_percentage=summary.on_base_percentage,
            slugging_percentage=summary.slugging_percentage,
            last_game_date=str(row["last_game_date"]) if row["last_game_date"] else None,
        )

    def close(self) -> None:
        return None
