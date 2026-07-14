"""PostgreSQL operational reads used by the FastAPI production shell."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Engine

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
            WHERE {" AND ".join(conditions)}
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
            WHERE {" AND ".join(conditions)}
            ORDER BY g.game_time_utc NULLS LAST, g.source_game_id
            LIMIT :limit
            """
        )
        with self._engine.connect() as connection:
            rows = connection.execute(statement, params).mappings()
            return [_weather_record(row) for row in rows]

    def get_game_weather(self, game_id: str) -> GameWeatherRecord | None:
        statement = text(f"{_WEATHER_SELECT} WHERE g.source_game_id = :game_id LIMIT 1")
        with self._engine.connect() as connection:
            row = connection.execute(statement, {"game_id": game_id}).mappings().first()
            return _weather_record(row) if row else None

    def get_players(
        self,
        *,
        query: str | None,
        role: str | None,
        season: int | None,
        limit: int,
        cursor: str | None,
    ) -> list[PlayerRecord]:
        conditions = ["p.name IS NOT NULL"]
        params: dict[str, object] = {"limit": limit}
        if query:
            conditions.append("p.name ILIKE :query")
            params["query"] = f"%{query}%"
        if cursor:
            conditions.append("p.provider_player_id > :cursor")
            params["cursor"] = int(cursor)
        batter_exists = (
            "EXISTS (SELECT 1 FROM batter_pitcher_game_logs b "
            "WHERE b.batter_id = p.id" + (" AND b.season = :season" if season else "") + ")"
        )
        pitcher_exists = (
            "EXISTS (SELECT 1 FROM pitcher_game_logs pg "
            "WHERE pg.pitcher_id = p.id" + (" AND pg.season = :season" if season else "") + ")"
        )
        if season:
            params["season"] = season
            conditions.append(f"({batter_exists} OR {pitcher_exists})")
        if role == "batter":
            conditions.append(batter_exists)
        elif role == "pitcher":
            conditions.append(pitcher_exists)
        elif role == "two-way":
            conditions.extend([batter_exists, pitcher_exists])
        statement = text(
            f"""
            {_PLAYER_SELECT}
            WHERE {" AND ".join(conditions)}
            ORDER BY p.provider_player_id
            LIMIT :limit
            """
        )
        with self._engine.connect() as connection:
            rows = connection.execute(statement, params).mappings()
            return [_player_record(row) for row in rows]

    def get_player(self, player_id: str) -> PlayerRecord | None:
        statement = text(f"{_PLAYER_SELECT} WHERE p.provider_player_id = :player_id LIMIT 1")
        with self._engine.connect() as connection:
            row = connection.execute(statement, {"player_id": int(player_id)}).mappings().first()
            return _player_record(row) if row else None

    def get_player_batting_summary(
        self, player_id: str, *, season: int | None
    ) -> BattingSummaryRecord | None:
        conditions = [
            "p.provider_player_id = :player_id",
            "b.season = COALESCE(CAST(:season AS INTEGER), ("
            "SELECT MAX(latest.season) FROM batter_pitcher_game_logs latest "
            "WHERE latest.batter_id = b.batter_id))",
        ]
        params: dict[str, object] = {
            "player_id": int(player_id),
            "season": season,
        }
        statement = text(
            f"""
            SELECT b.season,
                   COUNT(DISTINCT b.game_id) AS games,
                   SUM(b.pa) AS pa, SUM(b.ab) AS ab, SUM(b.hits) AS hits,
                   SUM(b.doubles) AS doubles, SUM(b.triples) AS triples,
                   SUM(b.walks) AS walks, SUM(b.hit_by_pitch) AS hit_by_pitch,
                   SUM(b.strikeouts) AS strikeouts, SUM(b.home_runs) AS home_runs,
                   SUM(b.rbi) AS rbi, SUM(b.total_bases) AS total_bases
            FROM batter_pitcher_game_logs b
            JOIN players p ON p.id = b.batter_id
            WHERE {" AND ".join(conditions)}
            GROUP BY b.season
            HAVING COUNT(*) > 0
            """
        )
        with self._engine.connect() as connection:
            row = connection.execute(statement, params).mappings().first()
            return _batting_summary(row) if row else None

    def get_player_pitching_summary(
        self, player_id: str, *, season: int | None
    ) -> PitchingSummaryRecord | None:
        conditions = ["p.provider_player_id = :player_id"]
        params: dict[str, object] = {"player_id": int(player_id), "season": season}
        if season:
            conditions.append("s.season = :season")
        statement = text(
            f"""
            SELECT s.* FROM pitcher_season_summaries s
            JOIN players p ON p.id = s.pitcher_id
            WHERE {" AND ".join(conditions)}
            ORDER BY s.season DESC LIMIT 1
            """
        )
        with self._engine.connect() as connection:
            row = connection.execute(statement, params).mappings().first()
            return _pitching_summary(row) if row else None

    def get_player_game_logs(
        self,
        player_id: str,
        *,
        season: int | None,
        group: str,
        limit: int,
    ) -> list[PlayerGameLogRecord]:
        if group == "pitching":
            statement = text(
                """
                SELECT g.source_game_id AS game_id, pg.game_date, pg.season,
                       opponent.name AS opponent, pg.is_starter, pg.innings_outs,
                       pg.pitch_count, pg.batters_faced, pg.hits, pg.walks,
                       pg.strikeouts, pg.home_runs, pg.runs, pg.earned_runs
                FROM pitcher_game_logs pg
                JOIN players p ON p.id = pg.pitcher_id
                JOIN games g ON g.id = pg.game_id
                LEFT JOIN teams opponent ON opponent.id = pg.opponent_team_id
                WHERE p.provider_player_id = :player_id
                  AND (CAST(:season AS INTEGER) IS NULL
                       OR pg.season = CAST(:season AS INTEGER))
                ORDER BY pg.game_date DESC, g.source_game_id DESC LIMIT :limit
                """
            )
        else:
            statement = text(
                """
                SELECT g.source_game_id AS game_id, b.game_date, b.season,
                       opponent.name AS opponent, COUNT(*) AS games,
                       SUM(b.pa) AS pa, SUM(b.ab) AS ab, SUM(b.hits) AS hits,
                       SUM(b.walks) AS walks, SUM(b.strikeouts) AS strikeouts,
                       SUM(b.home_runs) AS home_runs, SUM(b.rbi) AS rbi,
                       SUM(b.total_bases) AS total_bases
                FROM batter_pitcher_game_logs b
                JOIN players p ON p.id = b.batter_id
                JOIN games g ON g.id = b.game_id
                LEFT JOIN teams opponent ON opponent.id = b.pitching_team_id
                WHERE p.provider_player_id = :player_id
                  AND (CAST(:season AS INTEGER) IS NULL
                       OR b.season = CAST(:season AS INTEGER))
                GROUP BY g.source_game_id, b.game_date, b.season, opponent.name
                ORDER BY b.game_date DESC, g.source_game_id DESC LIMIT :limit
                """
            )
        with self._engine.connect() as connection:
            rows = connection.execute(
                statement,
                {"player_id": int(player_id), "season": season, "limit": limit},
            ).mappings()
            return [_player_game_log(row, group) for row in rows]

    def get_batter_pitcher_matchup(
        self,
        *,
        batter_id: str,
        pitcher_id: str,
        season: int | None,
    ) -> BatterPitcherMatchupRecord | None:
        statement = text(
            """
            SELECT batter.provider_player_id AS batter_id,
                   batter.name AS batter_name,
                   pitcher.provider_player_id AS pitcher_id,
                   pitcher.name AS pitcher_name,
                   CAST(:season AS INTEGER) AS season,
                   COUNT(DISTINCT b.game_id) AS games,
                   SUM(b.pa) AS pa, SUM(b.ab) AS ab, SUM(b.hits) AS hits,
                   SUM(b.doubles) AS doubles, SUM(b.triples) AS triples,
                   SUM(b.walks) AS walks, SUM(b.hit_by_pitch) AS hit_by_pitch,
                   SUM(b.strikeouts) AS strikeouts, SUM(b.home_runs) AS home_runs,
                   SUM(b.rbi) AS rbi, SUM(b.total_bases) AS total_bases,
                   MAX(b.game_date) AS last_game_date
            FROM batter_pitcher_game_logs b
            JOIN players batter ON batter.id = b.batter_id
            JOIN players pitcher ON pitcher.id = b.pitcher_id
            WHERE batter.provider_player_id = :batter_id
              AND pitcher.provider_player_id = :pitcher_id
              AND (CAST(:season AS INTEGER) IS NULL
                   OR b.season = CAST(:season AS INTEGER))
            GROUP BY batter.provider_player_id, batter.name,
                     pitcher.provider_player_id, pitcher.name
            """
        )
        with self._engine.connect() as connection:
            row = (
                connection.execute(
                    statement,
                    {
                        "batter_id": int(batter_id),
                        "pitcher_id": int(pitcher_id),
                        "season": season,
                    },
                )
                .mappings()
                .first()
            )
            return _matchup_record(row) if row else None

    def get_batter_pitcher_logs(
        self,
        *,
        batter_id: str,
        pitcher_id: str,
        season: int | None,
        limit: int,
    ) -> list[PlayerGameLogRecord]:
        statement = text(
            """
            SELECT g.source_game_id AS game_id, b.game_date, b.season,
                   opponent.name AS opponent, b.pa, b.ab, b.hits, b.walks,
                   b.strikeouts, b.home_runs, b.rbi, b.total_bases
            FROM batter_pitcher_game_logs b
            JOIN players batter ON batter.id = b.batter_id
            JOIN players pitcher ON pitcher.id = b.pitcher_id
            JOIN games g ON g.id = b.game_id
            LEFT JOIN teams opponent ON opponent.id = b.pitching_team_id
            WHERE batter.provider_player_id = :batter_id
              AND pitcher.provider_player_id = :pitcher_id
              AND (CAST(:season AS INTEGER) IS NULL
                   OR b.season = CAST(:season AS INTEGER))
            ORDER BY b.game_date DESC, g.source_game_id DESC LIMIT :limit
            """
        )
        with self._engine.connect() as connection:
            rows = connection.execute(
                statement,
                {
                    "batter_id": int(batter_id),
                    "pitcher_id": int(pitcher_id),
                    "season": season,
                    "limit": limit,
                },
            ).mappings()
            return [_player_game_log(row, "batting") for row in rows]

    def get_advanced_matchup(
        self,
        *,
        batter_id: str,
        pitcher_id: str,
        season: int | None,
        limit: int,
    ) -> dict[str, Any]:
        params = {
            "batter_id": int(batter_id),
            "pitcher_id": int(pitcher_id),
            "season": season,
            "limit": limit,
        }
        pitch_types = text(
            """
            SELECT s.season, s.pitch_type, s.pitch_name, s.pitch_count,
                   s.average_velocity, s.whiff_percentage, s.hard_hit_percentage,
                   s.barrel_percentage, s.expected_woba, s.last_game_date
            FROM batter_pitch_type_summaries s
            JOIN players batter ON batter.id = s.batter_id
            JOIN players pitcher ON pitcher.id = s.pitcher_id
            WHERE batter.provider_player_id = :batter_id
              AND pitcher.provider_player_id = :pitcher_id
              AND (CAST(:season AS INTEGER) IS NULL
                   OR s.season = CAST(:season AS INTEGER))
            ORDER BY s.pitch_count DESC, s.pitch_type LIMIT :limit
            """
        )
        sequences = text(
            """
            SELECT g.source_game_id AS game_id, s.game_date, s.at_bat_number,
                   s.result, s.pitch_count, s.pitch_sequence, s.launch_speed,
                   s.launch_angle, s.estimated_distance, s.barrel, s.hard_hit
            FROM plate_appearance_sequences s
            JOIN players batter ON batter.id = s.batter_id
            JOIN players pitcher ON pitcher.id = s.pitcher_id
            JOIN games g ON g.id = s.game_id
            WHERE batter.provider_player_id = :batter_id
              AND pitcher.provider_player_id = :pitcher_id
              AND (CAST(:season AS INTEGER) IS NULL
                   OR s.season = CAST(:season AS INTEGER))
            ORDER BY s.game_date DESC, s.at_bat_number DESC LIMIT :limit
            """
        )
        coverage = text(
            """
            SELECT COUNT(*) AS pitch_count, COUNT(DISTINCT e.game_id) AS games,
                   MAX(e.game_date) AS last_game_date
            FROM pitch_events e
            JOIN players batter ON batter.id = e.batter_id
            JOIN players pitcher ON pitcher.id = e.pitcher_id
            WHERE batter.provider_player_id = :batter_id
              AND pitcher.provider_player_id = :pitcher_id
              AND (CAST(:season AS INTEGER) IS NULL
                   OR e.season = CAST(:season AS INTEGER))
            """
        )
        with self._engine.connect() as connection:
            coverage_row = connection.execute(coverage, params).mappings().one()
            return {
                "coverage": _plain_row(coverage_row),
                "pitch_types": [
                    _plain_row(row) for row in connection.execute(pitch_types, params).mappings()
                ],
                "sequences": [
                    _plain_row(row) for row in connection.execute(sequences, params).mappings()
                ],
            }

    def get_pitcher_opponent(
        self,
        *,
        pitcher_id: str,
        team: str | None,
        season: int | None,
        limit: int,
    ) -> dict[str, Any]:
        conditions = [
            "p.provider_player_id = :pitcher_id",
            "(CAST(:season AS INTEGER) IS NULL OR pg.season = CAST(:season AS INTEGER))",
            "(CAST(:team AS TEXT) IS NULL "
            "OR upper(opponent.abbreviation) = upper(CAST(:team AS TEXT)) "
            "OR upper(opponent.name) = upper(CAST(:team AS TEXT)))",
        ]
        params = {
            "pitcher_id": int(pitcher_id),
            "team": team,
            "season": season,
            "limit": limit,
        }
        summary = text(
            f"""
            SELECT p.provider_player_id AS pitcher_id, p.name AS pitcher_name,
                   opponent.abbreviation AS opponent, COUNT(*) AS games,
                   SUM(pg.innings_outs) AS innings_outs,
                   SUM(pg.batters_faced) AS batters_faced,
                   SUM(pg.strikeouts) AS strikeouts, SUM(pg.walks) AS walks,
                   SUM(pg.hits) AS hits, SUM(pg.home_runs) AS home_runs,
                   SUM(pg.runs) AS runs, SUM(pg.earned_runs) AS earned_runs,
                   MAX(pg.game_date) AS last_game_date
            FROM pitcher_game_logs pg
            JOIN players p ON p.id = pg.pitcher_id
            LEFT JOIN teams opponent ON opponent.id = pg.opponent_team_id
            WHERE {" AND ".join(conditions)}
            GROUP BY p.provider_player_id, p.name, opponent.abbreviation
            ORDER BY COUNT(*) DESC, opponent.abbreviation NULLS LAST
            LIMIT :limit
            """
        )
        logs = text(
            f"""
            SELECT g.source_game_id AS game_id, pg.game_date, pg.season,
                   opponent.abbreviation AS opponent, pg.is_starter,
                   pg.innings_outs, pg.pitch_count, pg.batters_faced,
                   pg.hits, pg.walks, pg.strikeouts, pg.home_runs,
                   pg.runs, pg.earned_runs
            FROM pitcher_game_logs pg
            JOIN players p ON p.id = pg.pitcher_id
            JOIN games g ON g.id = pg.game_id
            LEFT JOIN teams opponent ON opponent.id = pg.opponent_team_id
            WHERE {" AND ".join(conditions)}
            ORDER BY pg.game_date DESC, g.source_game_id DESC LIMIT :limit
            """
        )
        with self._engine.connect() as connection:
            return {
                "splits": [
                    _plain_row(row) for row in connection.execute(summary, params).mappings()
                ],
                "game_logs": [
                    _plain_row(row) for row in connection.execute(logs, params).mappings()
                ],
            }

    def get_bullpen_projection(
        self, *, game_id: str, team: str | None, batter_id: str | None
    ) -> list[dict[str, Any]]:
        statement = text(
            """
            SELECT g.source_game_id AS game_id, t.abbreviation AS team,
                   p.provider_player_id AS pitcher_id, p.name AS pitcher_name,
                   item.projected_role, item.availability_score,
                   item.availability_label, item.appearance_probability,
                   item.expected_batters_faced_min, item.expected_batters_faced_max,
                   item.recent_workload, item.reason, run.generation,
                   bvp.pa AS batter_pa, bvp.hits AS batter_hits,
                   bvp.home_runs AS batter_home_runs, bvp.strikeouts AS batter_strikeouts
            FROM bullpen_projection_items item
            JOIN bullpen_projection_runs run ON run.id = item.run_id
            JOIN games g ON g.id = item.game_id
            JOIN teams t ON t.id = item.team_id
            JOIN players p ON p.id = item.pitcher_id
            LEFT JOIN players batter ON batter.provider_player_id = CAST(:batter_id AS BIGINT)
            LEFT JOIN batter_pitcher_summaries bvp
              ON bvp.batter_id = batter.id AND bvp.pitcher_id = p.id
            WHERE g.source_game_id = :game_id
              AND (CAST(:team AS TEXT) IS NULL
                   OR upper(t.abbreviation) = upper(CAST(:team AS TEXT)))
              AND run.id = (
                  SELECT latest.id FROM bullpen_projection_runs latest
                  JOIN bullpen_projection_items latest_item ON latest_item.run_id = latest.id
                  WHERE latest_item.game_id = g.id
                  ORDER BY latest.active DESC, latest.created_at DESC LIMIT 1
              )
            ORDER BY item.appearance_probability DESC NULLS LAST, p.name
            """
        )
        with self._engine.connect() as connection:
            rows = connection.execute(
                statement, {"game_id": game_id, "team": team, "batter_id": batter_id}
            ).mappings()
            return [_plain_row(row) for row in rows]

    def get_streaks(
        self,
        *,
        through_date: str | None,
        group: str,
        metric: str,
        limit: int,
    ) -> list[dict[str, Any]]:
        statement = text(
            """
            SELECT s.through_date, s.group_name AS "group", s.metric,
                   COALESCE(p.provider_player_id::text, t.provider_team_id::text) AS subject_id,
                   COALESCE(p.name, t.name) AS subject_name, t.abbreviation AS team,
                   s.streak, s.last_game_date
            FROM streak_summaries s
            LEFT JOIN players p ON p.id = s.player_id
            LEFT JOIN teams t ON t.id = s.team_id
            WHERE s.group_name = :group AND s.metric = :metric
              AND s.through_date = COALESCE(
                  CAST(:through_date AS DATE),
                  (SELECT MAX(latest.through_date) FROM streak_summaries latest
                   WHERE latest.group_name = :group AND latest.metric = :metric)
              )
            ORDER BY s.streak DESC, subject_name LIMIT :limit
            """
        )
        with self._engine.connect() as connection:
            rows = connection.execute(
                statement,
                {"through_date": through_date, "group": group, "metric": metric, "limit": limit},
            ).mappings()
            return [_plain_row(row) for row in rows]

    def get_player_leaderboard(
        self,
        *,
        season: int | None,
        group: str,
        sort: str,
        query: str | None,
        limit: int,
    ) -> list[dict[str, Any]]:
        if group == "pitching":
            sort_column = {
                "strikeouts": "s.strikeouts",
                "era": "s.earned_run_average",
                "whip": "s.whip",
                "innings": "s.innings_outs",
            }.get(sort, "s.strikeouts")
            statement = text(
                f"""
                SELECT s.season, p.provider_player_id AS player_id, p.name,
                       s.games, s.starts, s.innings_outs, s.strikeouts,
                       s.earned_run_average AS era, s.whip, s.walks, s.home_runs,
                       s.last_game_date
                FROM pitcher_season_summaries s JOIN players p ON p.id = s.pitcher_id
                WHERE s.season = COALESCE(CAST(:season AS INTEGER),
                    (SELECT MAX(season) FROM pitcher_season_summaries))
                  AND (CAST(:query AS TEXT) IS NULL OR p.name ILIKE CAST(:query AS TEXT))
                ORDER BY {sort_column} {"ASC" if sort in {"era", "whip"} else "DESC"}
                         NULLS LAST, p.name LIMIT :limit
                """
            )
        else:
            sort_column = {
                "home_runs": "s.home_runs",
                "hits": "s.hits",
                "rbi": "s.rbi",
                "average": "(s.hits::numeric / NULLIF(s.ab, 0))",
                "ops": "((s.hits + s.walks + s.hit_by_pitch)::numeric / NULLIF(s.pa, 0) "
                "+ s.total_bases::numeric / NULLIF(s.ab, 0))",
            }.get(sort, "s.home_runs")
            statement = text(
                f"""
                SELECT s.season, p.provider_player_id AS player_id, p.name,
                       t.abbreviation AS team, s.games, s.pa, s.ab, s.hits,
                       s.home_runs, s.rbi, s.walks, s.strikeouts, s.total_bases,
                       ROUND(s.hits::numeric / NULLIF(s.ab, 0), 3) AS average,
                       ROUND((s.hits + s.walks + s.hit_by_pitch)::numeric / NULLIF(s.pa, 0)
                           + s.total_bases::numeric / NULLIF(s.ab, 0), 3) AS ops,
                       s.last_game_date
                FROM batter_season_summaries s JOIN players p ON p.id = s.batter_id
                LEFT JOIN teams t ON t.id = s.team_id
                WHERE s.season = COALESCE(CAST(:season AS INTEGER),
                    (SELECT MAX(season) FROM batter_season_summaries))
                  AND (CAST(:query AS TEXT) IS NULL OR p.name ILIKE CAST(:query AS TEXT))
                ORDER BY {sort_column} DESC NULLS LAST, p.name LIMIT :limit
                """
            )
        params = {
            "season": season,
            "query": f"%{query}%" if query else None,
            "limit": limit,
        }
        with self._engine.connect() as connection:
            return [_plain_row(row) for row in connection.execute(statement, params).mappings()]

    def get_team_leaderboard(
        self, *, season: int | None, group: str, sort: str, limit: int
    ) -> list[dict[str, Any]]:
        batting_sorts = {
            "runs": "s.runs",
            "home_runs": "s.home_runs",
            "average": "s.hits::numeric / NULLIF(s.pa - s.walks, 0)",
            "strikeout_rate": "s.strikeouts::numeric / NULLIF(s.pa, 0)",
        }
        pitching_sorts = {
            "era": "s.earned_runs_allowed * 27.0 / NULLIF(s.innings_outs, 0)",
            "strikeouts": "s.strikeouts_pitched",
            "runs_allowed": "s.runs_allowed",
            "walks_allowed": "s.walks_allowed",
        }
        sort_column = (
            pitching_sorts.get(sort, "s.earned_runs_allowed * 27.0 / NULLIF(s.innings_outs, 0)")
            if group == "pitching"
            else batting_sorts.get(sort, "s.runs")
        )
        ascending = sort in {"era", "runs_allowed", "walks_allowed", "strikeout_rate"}
        statement = text(
            f"""
            SELECT s.season, t.provider_team_id AS team_id, t.name,
                   t.abbreviation, s.games, s.pa, s.runs, s.hits, s.walks,
                   s.strikeouts, s.home_runs, s.innings_outs, s.runs_allowed,
                   s.earned_runs_allowed, s.hits_allowed, s.walks_allowed,
                   s.strikeouts_pitched, s.home_runs_allowed,
                   ROUND(s.hits::numeric / NULLIF(s.pa - s.walks, 0), 3) AS average,
                   ROUND(s.earned_runs_allowed * 27.0 / NULLIF(s.innings_outs, 0), 2) AS era,
                   s.last_game_date
            FROM team_season_summaries s JOIN teams t ON t.id = s.team_id
            WHERE s.season = COALESCE(CAST(:season AS INTEGER),
                (SELECT MAX(season) FROM team_season_summaries))
            ORDER BY {sort_column} {"ASC" if ascending else "DESC"} NULLS LAST, t.name
            LIMIT :limit
            """
        )
        with self._engine.connect() as connection:
            return [
                _plain_row(row)
                for row in connection.execute(
                    statement, {"season": season, "limit": limit}
                ).mappings()
            ]

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

_PLAYER_SELECT = """
    SELECT p.provider_player_id AS player_id, p.name, p.active_status,
           CASE
             WHEN EXISTS (SELECT 1 FROM batter_pitcher_game_logs b WHERE b.batter_id=p.id)
              AND EXISTS (SELECT 1 FROM pitcher_game_logs pg WHERE pg.pitcher_id=p.id)
               THEN 'two-way'
             WHEN EXISTS (SELECT 1 FROM pitcher_game_logs pg WHERE pg.pitcher_id=p.id)
               THEN 'pitcher'
             WHEN EXISTS (SELECT 1 FROM batter_pitcher_game_logs b WHERE b.batter_id=p.id)
               THEN 'batter'
             ELSE 'unknown'
           END AS player_type,
           GREATEST(
             (SELECT MAX(b.season) FROM batter_pitcher_game_logs b WHERE b.batter_id=p.id),
             (SELECT MAX(pg.season) FROM pitcher_game_logs pg WHERE pg.pitcher_id=p.id)
           ) AS latest_season,
           GREATEST(
             (SELECT MAX(b.game_date) FROM batter_pitcher_game_logs b WHERE b.batter_id=p.id),
             (SELECT MAX(pg.game_date) FROM pitcher_game_logs pg WHERE pg.pitcher_id=p.id)
           ) AS last_game_date
    FROM players p
"""


def _text_value(value: object | None) -> str | None:
    return str(value) if value is not None else None


def _float_value(value: Any) -> float | None:
    return float(value) if value is not None else None


def _game_record(row: Mapping[Any, Any]) -> GameRecord:
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


def _weather_record(row: Mapping[Any, Any]) -> GameWeatherRecord:
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


def _player_record(row: Mapping[Any, Any]) -> PlayerRecord:
    return PlayerRecord(
        player_id=str(row["player_id"]),
        name=_text_value(row["name"]),
        active_status=str(row["active_status"]),
        player_type=str(row["player_type"]),
        latest_season=int(row["latest_season"]) if row["latest_season"] is not None else None,
        last_game_date=_text_value(row["last_game_date"]),
    )


def _ratio(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 5) if denominator else None


def _plain_row(row: Mapping[Any, Any]) -> dict[str, Any]:
    plain: dict[str, Any] = {}
    for key, value in row.items():
        if isinstance(value, Decimal):
            plain[str(key)] = float(value)
        elif isinstance(value, (date, datetime)):
            plain[str(key)] = value.isoformat()
        else:
            plain[str(key)] = value
    return plain


def _batting_summary(row: Mapping[Any, Any]) -> BattingSummaryRecord:
    pa = int(row["pa"] or 0)
    ab = int(row["ab"] or 0)
    hits = int(row["hits"] or 0)
    walks = int(row["walks"] or 0)
    hit_by_pitch = int(row["hit_by_pitch"] or 0)
    total_bases = int(row["total_bases"] or 0)
    return BattingSummaryRecord(
        season=int(row["season"]),
        games=int(row["games"] or 0),
        pa=pa,
        ab=ab,
        hits=hits,
        doubles=int(row["doubles"] or 0),
        triples=int(row["triples"] or 0),
        walks=walks,
        hit_by_pitch=hit_by_pitch,
        strikeouts=int(row["strikeouts"] or 0),
        home_runs=int(row["home_runs"] or 0),
        rbi=int(row["rbi"] or 0),
        total_bases=total_bases,
        batting_average=_ratio(hits, ab),
        on_base_percentage=_ratio(hits + walks + hit_by_pitch, pa),
        slugging_percentage=_ratio(total_bases, ab),
    )


def _pitching_summary(row: Mapping[Any, Any]) -> PitchingSummaryRecord:
    return PitchingSummaryRecord(
        season=int(row["season"]),
        games=int(row["games"]),
        starts=int(row["starts"]),
        innings_outs=int(row["innings_outs"]),
        pitch_count=int(row["pitch_count"]),
        batters_faced=int(row["batters_faced"]),
        hits=int(row["hits"]),
        walks=int(row["walks"]),
        hit_by_pitch=int(row["hit_by_pitch"]),
        strikeouts=int(row["strikeouts"]),
        home_runs=int(row["home_runs"]),
        runs=int(row["runs"]),
        earned_runs=int(row["earned_runs"]),
        earned_run_average=_float_value(row["earned_run_average"]),
        whip=_float_value(row["whip"]),
    )


def _player_game_log(row: Mapping[Any, Any], group: str) -> PlayerGameLogRecord:
    def integer(name: str) -> int | None:
        value = row.get(name)
        return int(value) if value is not None else None

    return PlayerGameLogRecord(
        game_id=str(row["game_id"]),
        game_date=str(row["game_date"]),
        season=int(row["season"]),
        group=group,
        opponent=_text_value(row.get("opponent")),
        games=integer("games") or 1,
        pa=integer("pa"),
        ab=integer("ab"),
        hits=integer("hits"),
        walks=integer("walks"),
        strikeouts=integer("strikeouts"),
        home_runs=integer("home_runs"),
        rbi=integer("rbi"),
        total_bases=integer("total_bases"),
        is_starter=bool(row["is_starter"]) if row.get("is_starter") is not None else None,
        innings_outs=integer("innings_outs"),
        pitch_count=integer("pitch_count"),
        batters_faced=integer("batters_faced"),
        runs=integer("runs"),
        earned_runs=integer("earned_runs"),
    )


def _matchup_record(row: Mapping[Any, Any]) -> BatterPitcherMatchupRecord:
    ab = int(row["ab"] or 0)
    pa = int(row["pa"] or 0)
    hits = int(row["hits"] or 0)
    walks = int(row["walks"] or 0)
    hit_by_pitch = int(row["hit_by_pitch"] or 0)
    total_bases = int(row["total_bases"] or 0)
    return BatterPitcherMatchupRecord(
        batter_id=str(row["batter_id"]),
        batter_name=_text_value(row["batter_name"]),
        pitcher_id=str(row["pitcher_id"]),
        pitcher_name=_text_value(row["pitcher_name"]),
        season=int(row["season"]) if row["season"] is not None else None,
        games=int(row["games"]),
        pa=pa,
        ab=ab,
        hits=hits,
        doubles=int(row["doubles"] or 0),
        triples=int(row["triples"] or 0),
        walks=walks,
        hit_by_pitch=hit_by_pitch,
        strikeouts=int(row["strikeouts"] or 0),
        home_runs=int(row["home_runs"] or 0),
        rbi=int(row["rbi"] or 0),
        total_bases=total_bases,
        batting_average=_ratio(hits, ab),
        on_base_percentage=_ratio(hits + walks + hit_by_pitch, pa),
        slugging_percentage=_ratio(total_bases, ab),
        last_game_date=_text_value(row["last_game_date"]),
    )
