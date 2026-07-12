"""Chunked, read-only migration from a pinned legacy SQLite snapshot."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
from collections.abc import Iterator, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import psycopg
from psycopg import Cursor
from psycopg.types.json import Jsonb

REQUIRED_TABLES = {
    "batter_pitcher_game_logs",
    "daily_bullpen_projections",
    "games",
    "live_game_contacts",
    "players",
    "pitcher_game_logs",
    "refresh_log",
}


class MigrationError(RuntimeError):
    """Raised before commit when a migration invariant is violated."""


@dataclass(frozen=True, slots=True)
class SnapshotAudit:
    path: str
    sha256: str
    size_bytes: int
    quick_check: str
    table_counts: dict[str, int]
    index_names: tuple[str, ...]
    game_source_counts: dict[str, int]
    fact_totals: dict[str, int]
    min_game_date: str | None
    max_game_date: str | None
    min_season: int | None
    max_season: int | None
    orphan_counts: dict[str, int]
    quarantined_counts: dict[str, int]

    @property
    def generation(self) -> str:
        return f"sqlite-{self.sha256[:16]}"


@dataclass(frozen=True, slots=True)
class MigrationReport:
    audit: SnapshotAudit
    target_counts: dict[str, int]
    target_orphan_counts: dict[str, int]
    target_fact_totals: dict[str, int]
    completed_at: str


def _snapshot_uri(path: Path) -> str:
    resolved = path.resolve()
    return f"file:{resolved.as_posix()}?mode=ro&immutable=1"


def open_snapshot(path: Path) -> sqlite3.Connection:
    if not path.is_file():
        raise MigrationError(f"Snapshot does not exist: {path}")
    wal_path = Path(f"{path}-wal")
    if wal_path.exists() and wal_path.stat().st_size:
        raise MigrationError("Snapshot has a non-empty WAL; checkpoint and copy it first")
    connection = sqlite3.connect(_snapshot_uri(path), uri=True)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only = ON")
    return connection


def sha256_file(path: Path, *, chunk_bytes: int = 8 * 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(chunk_bytes):
            digest.update(chunk)
    return digest.hexdigest()


def _scalar(connection: sqlite3.Connection, sql: str) -> Any:
    return connection.execute(sql).fetchone()[0]


def _sqlite_identifier(name: str) -> str:
    return f'"{name.replace(chr(34), chr(34) * 2)}"'


def audit_snapshot(path: Path) -> SnapshotAudit:
    with open_snapshot(path) as connection:
        quick_check = str(_scalar(connection, "PRAGMA quick_check"))
        table_names = {
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )
        }
        missing = REQUIRED_TABLES - table_names
        if missing:
            raise MigrationError(f"Snapshot is missing required tables: {sorted(missing)}")
        table_counts = {
            name: int(_scalar(connection, f"SELECT COUNT(*) FROM {_sqlite_identifier(name)}"))
            for name in sorted(table_names)
        }
        index_names = tuple(
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='index' ORDER BY name"
            )
            if row[0]
        )
        game_source_counts = {
            str(source): int(count)
            for source, count in connection.execute(
                "SELECT source, COUNT(*) FROM games GROUP BY source ORDER BY source"
            )
        }
        fact_totals = {
            "bvp_pa": int(
                _scalar(connection, "SELECT COALESCE(SUM(PA), 0) FROM batter_pitcher_game_logs")
            ),
            "bvp_ab": int(
                _scalar(connection, "SELECT COALESCE(SUM(AB), 0) FROM batter_pitcher_game_logs")
            ),
            "bvp_hits": int(
                _scalar(connection, "SELECT COALESCE(SUM(H), 0) FROM batter_pitcher_game_logs")
            ),
            "bvp_strikeouts": int(
                _scalar(connection, "SELECT COALESCE(SUM(SO), 0) FROM batter_pitcher_game_logs")
            ),
            "bvp_home_runs": int(
                _scalar(connection, "SELECT COALESCE(SUM(HR), 0) FROM batter_pitcher_game_logs")
            ),
            "bvp_total_bases": int(
                _scalar(connection, "SELECT COALESCE(SUM(TB), 0) FROM batter_pitcher_game_logs")
            ),
            "pitcher_innings_outs": int(
                _scalar(connection, "SELECT COALESCE(SUM(IP_outs), 0) FROM pitcher_game_logs")
            ),
            "pitcher_batters_faced": int(
                _scalar(connection, "SELECT COALESCE(SUM(BF), 0) FROM pitcher_game_logs")
            ),
            "pitcher_hits": int(
                _scalar(connection, "SELECT COALESCE(SUM(H), 0) FROM pitcher_game_logs")
            ),
            "pitcher_walks": int(
                _scalar(connection, "SELECT COALESCE(SUM(BB), 0) FROM pitcher_game_logs")
            ),
            "pitcher_strikeouts": int(
                _scalar(connection, "SELECT COALESCE(SUM(SO), 0) FROM pitcher_game_logs")
            ),
            "pitcher_earned_runs": int(
                _scalar(connection, "SELECT COALESCE(SUM(ER), 0) FROM pitcher_game_logs")
            ),
        }
        date_range = connection.execute(
            "SELECT MIN(game_date), MAX(game_date), MIN(season), MAX(season) FROM games"
        ).fetchone()
        orphan_counts = {
            "bvp_games": int(
                _scalar(
                    connection,
                    "SELECT COUNT(*) FROM batter_pitcher_game_logs l "
                    "LEFT JOIN games g ON g.game_pk=l.game_pk WHERE g.game_pk IS NULL",
                )
            ),
            "pitcher_games": int(
                _scalar(
                    connection,
                    "SELECT COUNT(*) FROM pitcher_game_logs l "
                    "LEFT JOIN games g ON g.game_pk=l.game_pk WHERE g.game_pk IS NULL",
                )
            ),
            "bvp_players": int(
                _scalar(
                    connection,
                    "SELECT COUNT(*) FROM batter_pitcher_game_logs l "
                    "LEFT JOIN players b ON b.player_id=l.batter_id "
                    "LEFT JOIN players p ON p.player_id=l.pitcher_id "
                    "WHERE b.player_id IS NULL OR p.player_id IS NULL",
                )
            ),
            "noncanonical_games": int(
                _scalar(
                    connection,
                    "SELECT COUNT(*) FROM games WHERE game_id NOT LIKE 'mlb:%' "
                    "AND game_id NOT LIKE 'retro:%'",
                )
            ),
        }
        quarantined_counts = {
            "live_game_contacts_without_game": int(
                _scalar(
                    connection,
                    "SELECT COUNT(*) FROM live_game_contacts l "
                    "LEFT JOIN games g ON g.game_pk=l.game_pk WHERE g.game_pk IS NULL",
                )
            ),
            "bullpen_projections_without_game": int(
                _scalar(
                    connection,
                    "SELECT COUNT(*) FROM daily_bullpen_projections l "
                    "LEFT JOIN games g ON g.game_pk=l.game_pk WHERE g.game_pk IS NULL",
                )
            ),
        }
    if quick_check != "ok":
        raise MigrationError(f"SQLite quick_check failed: {quick_check}")
    if any(orphan_counts.values()):
        raise MigrationError(f"Snapshot referential audit failed: {orphan_counts}")
    return SnapshotAudit(
        path=str(path.resolve()),
        sha256=sha256_file(path),
        size_bytes=path.stat().st_size,
        quick_check=quick_check,
        table_counts=table_counts,
        index_names=index_names,
        game_source_counts=game_source_counts,
        fact_totals=fact_totals,
        min_game_date=str(date_range[0]) if date_range[0] else None,
        max_game_date=str(date_range[1]) if date_range[1] else None,
        min_season=int(date_range[2]) if date_range[2] is not None else None,
        max_season=int(date_range[3]) if date_range[3] is not None else None,
        orphan_counts=orphan_counts,
        quarantined_counts=quarantined_counts,
    )


def canonical_game_identity(row: sqlite3.Row | dict[str, Any]) -> tuple[str, int | None]:
    source_game_id = str(row["game_id"] or "")
    legacy_game_pk = int(row["game_pk"])
    if source_game_id.startswith("mlb:"):
        try:
            return source_game_id, int(source_game_id.removeprefix("mlb:"))
        except ValueError as exc:
            raise MigrationError(f"Invalid MLB game ID: {source_game_id}") from exc
    if source_game_id.startswith("retro:"):
        return source_game_id, None
    raise MigrationError(f"Noncanonical game ID for legacy key {legacy_game_pk}")


def iter_rows(
    connection: sqlite3.Connection,
    sql: str,
    *,
    chunk_size: int,
) -> Iterator[sqlite3.Row]:
    cursor = connection.execute(sql)
    while rows := cursor.fetchmany(chunk_size):
        yield from rows


def _team_catalog(connection: sqlite3.Connection) -> dict[str, tuple[str, int | None]]:
    catalog: dict[str, tuple[str, int | None]] = {}
    rows = connection.execute(
        "SELECT away_team, away_team_id FROM games "
        "UNION ALL SELECT home_team, home_team_id FROM games"
    )
    for abbreviation, provider_id in rows:
        key = str(abbreviation or "").strip().upper()
        if not key:
            raise MigrationError("Every game must have home and away team text")
        numeric_id = int(provider_id) if provider_id is not None else None
        current = catalog.get(key)
        current_id = current[1] if current else None
        if current_id is not None and numeric_id is not None and current_id != numeric_id:
            raise MigrationError(f"Team abbreviation {key} maps to multiple provider IDs")
        if key not in catalog or numeric_id is not None:
            catalog[key] = (str(abbreviation).strip(), numeric_id)
    return catalog


def _target_map(cursor: Cursor[Any], sql: str) -> dict[Any, int]:
    cursor.execute(sql)
    return {key: int(identifier) for key, identifier in cursor.fetchall()}


def _target_scalar(cursor: Cursor[Any]) -> Any:
    row = cursor.fetchone()
    if row is None:
        raise MigrationError("Target query returned no scalar row")
    return row[0]


def _as_int(value: Any) -> int:
    return int(value or 0)


def _as_json(value: Any) -> Jsonb | None:
    if not value:
        return None
    try:
        parsed = json.loads(str(value))
    except json.JSONDecodeError:
        parsed = {"legacy_payload": str(value)}
    return Jsonb(parsed)


RANGE_PATTERN = re.compile(r"(?P<minimum>\d+)\D+(?P<maximum>\d+)")


def parse_workload_range(value: Any) -> tuple[int | None, int | None]:
    if not value:
        return None, None
    match = RANGE_PATTERN.search(str(value))
    if not match:
        return None, None
    return int(match["minimum"]), int(match["maximum"])


def _copy_bvp(
    source: sqlite3.Connection,
    target: Cursor[Any],
    game_map: dict[int, int],
    player_map: dict[int, int],
    team_map: dict[str, int],
    *,
    chunk_size: int,
) -> None:
    sql = """
        COPY batter_pitcher_game_logs (
            game_id, game_date, season, batter_id, pitcher_id,
            batting_team_id, pitching_team_id, source, pa, ab, hits,
            doubles, triples, walks, hit_by_pitch, strikeouts, home_runs,
            rbi, sacrifice_flies, total_bases
        ) FROM STDIN
    """
    select_sql = """
        SELECT game_pk, game_date, season, batter_id, pitcher_id,
               batting_team, pitching_team, source, PA, AB, H, doubles,
               triples, BB, HBP, SO, HR, RBI, SF, TB
        FROM batter_pitcher_game_logs ORDER BY game_pk, batter_id, pitcher_id
    """
    with target.copy(sql) as copy:
        for row in iter_rows(source, select_sql, chunk_size=chunk_size):
            copy.write_row(
                (
                    game_map[int(row["game_pk"])],
                    row["game_date"],
                    int(row["season"]),
                    player_map[int(row["batter_id"])],
                    player_map[int(row["pitcher_id"])],
                    team_map.get(str(row["batting_team"] or "").upper()),
                    team_map.get(str(row["pitching_team"] or "").upper()),
                    row["source"],
                    *(
                        _as_int(row[name])
                        for name in (
                            "PA",
                            "AB",
                            "H",
                            "doubles",
                            "triples",
                            "BB",
                            "HBP",
                            "SO",
                            "HR",
                            "RBI",
                            "SF",
                            "TB",
                        )
                    ),
                )
            )


def _copy_pitchers(
    source: sqlite3.Connection,
    target: Cursor[Any],
    game_map: dict[int, int],
    player_map: dict[int, int],
    team_map: dict[str, int],
    *,
    chunk_size: int,
) -> None:
    sql = """
        COPY pitcher_game_logs (
            game_id, game_date, season, pitcher_id, team_id, opponent_team_id,
            source, is_starter, innings_outs, pitch_count, batters_faced,
            hits, walks, hit_by_pitch, strikeouts, home_runs, runs, earned_runs
        ) FROM STDIN
    """
    select_sql = """
        SELECT game_pk, game_date, season, pitcher_id, team, opponent, source,
               is_starter, IP_outs, pitch_count, BF, H, BB, HBP, SO, HR, R, ER
        FROM pitcher_game_logs ORDER BY game_pk, pitcher_id
    """
    with target.copy(sql) as copy:
        for row in iter_rows(source, select_sql, chunk_size=chunk_size):
            copy.write_row(
                (
                    game_map[int(row["game_pk"])],
                    row["game_date"],
                    int(row["season"]),
                    player_map[int(row["pitcher_id"])],
                    team_map.get(str(row["team"] or "").upper()),
                    team_map.get(str(row["opponent"] or "").upper()),
                    row["source"],
                    bool(row["is_starter"]),
                    _as_int(row["IP_outs"]),
                    int(row["pitch_count"]) if row["pitch_count"] is not None else None,
                    *(
                        _as_int(row[name])
                        for name in (
                            "BF",
                            "H",
                            "BB",
                            "HBP",
                            "SO",
                            "HR",
                            "R",
                            "ER",
                        )
                    ),
                )
            )


def _rebuild_summaries(target: Cursor[Any], generation: str) -> None:
    target.execute(
        """
        INSERT INTO batter_pitcher_summaries (
            batter_id, pitcher_id, pa, ab, hits, doubles, triples, walks,
            hit_by_pitch, strikeouts, home_runs, rbi, sacrifice_flies,
            total_bases, batting_average, on_base_percentage,
            slugging_percentage, last_game_date, generation
        )
        SELECT batter_id, pitcher_id, SUM(pa), SUM(ab), SUM(hits), SUM(doubles),
               SUM(triples), SUM(walks), SUM(hit_by_pitch), SUM(strikeouts),
               SUM(home_runs), SUM(rbi), SUM(sacrifice_flies), SUM(total_bases),
               SUM(hits)::numeric / NULLIF(SUM(ab), 0),
               (SUM(hits)+SUM(walks)+SUM(hit_by_pitch))::numeric /
                   NULLIF(SUM(ab)+SUM(walks)+SUM(hit_by_pitch)+SUM(sacrifice_flies), 0),
               SUM(total_bases)::numeric / NULLIF(SUM(ab), 0),
               MAX(game_date), %s
        FROM batter_pitcher_game_logs GROUP BY batter_id, pitcher_id
        """,
        (generation,),
    )
    target.execute(
        """
        INSERT INTO pitcher_season_summaries (
            season, pitcher_id, games, starts, innings_outs, pitch_count,
            batters_faced, hits, walks, hit_by_pitch, strikeouts, home_runs,
            runs, earned_runs, earned_run_average, whip, last_game_date, generation
        )
        SELECT season, pitcher_id, COUNT(*), COUNT(*) FILTER (WHERE is_starter),
               SUM(innings_outs), COALESCE(SUM(pitch_count), 0),
               SUM(batters_faced), SUM(hits), SUM(walks), SUM(hit_by_pitch),
               SUM(strikeouts), SUM(home_runs), SUM(runs), SUM(earned_runs),
               27.0 * SUM(earned_runs) / NULLIF(SUM(innings_outs), 0),
               3.0 * (SUM(walks)+SUM(hits)) / NULLIF(SUM(innings_outs), 0),
               MAX(game_date), %s
        FROM pitcher_game_logs GROUP BY season, pitcher_id
        """,
        (generation,),
    )


def _load_small_tables(
    source: sqlite3.Connection,
    target: Cursor[Any],
    game_map: dict[int, int],
    player_map: dict[int, int],
    team_provider_map: dict[int, int],
    generation: str,
) -> dict[str, int]:
    quarantined = {
        "live_game_contacts_without_game": 0,
        "bullpen_projections_without_game": 0,
    }
    for row in source.execute("SELECT * FROM live_game_contacts ORDER BY game_pk, play_key"):
        if int(row["game_pk"]) not in game_map:
            quarantined["live_game_contacts_without_game"] += 1
            continue
        target.execute(
            """
            INSERT INTO live_game_contacts (
                game_id, play_key, play_index, inning, half_inning, batter_id,
                pitcher_id, result_type, description, runs_scored, launch_speed,
                launch_angle, distance, provider_residual, source_updated_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                game_map[int(row["game_pk"])],
                row["play_key"],
                row["play_index"],
                row["inning"],
                row["half_inning"],
                player_map.get(int(row["batter_id"])) if row["batter_id"] else None,
                player_map.get(int(row["pitcher_id"])) if row["pitcher_id"] else None,
                row["result_type"],
                row["description"],
                row["runs_scored"],
                row["launch_speed"],
                row["launch_angle"],
                row["distance"],
                _as_json(row["payload_json"]),
                row["updated_at"],
            ),
        )
    run_ids: dict[str, int] = {}
    for row in source.execute("SELECT * FROM daily_bullpen_projections ORDER BY game_date"):
        if int(row["game_pk"]) not in game_map:
            quarantined["bullpen_projections_without_game"] += 1
            continue
        run_key = str(row["game_date"])
        if run_key not in run_ids:
            target.execute(
                """INSERT INTO bullpen_projection_runs
                   (game_date, generation, created_at, active)
                   VALUES (%s, %s, %s, FALSE) RETURNING id""",
                (run_key, f"{generation}-{run_key}", row["projection_timestamp"]),
            )
            run_ids[run_key] = int(_target_scalar(target))
        minimum, maximum = parse_workload_range(row["expected_batters_faced_range"])
        target.execute(
            """
            INSERT INTO bullpen_projection_items (
                run_id, game_id, team_id, pitcher_id, projected_role,
                availability_score, availability_label, appearance_probability,
                expected_batters_faced_min, expected_batters_faced_max,
                recent_workload, reason
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                run_ids[run_key],
                game_map[int(row["game_pk"])],
                team_provider_map[int(row["team_id"])],
                player_map[int(row["pitcher_id"])],
                row["projected_role"],
                row["availability_score"],
                row["availability_label"],
                row["appearance_probability"],
                minimum,
                maximum,
                row["recent_workload"],
                row["projection_reason"],
            ),
        )
    for row in source.execute("SELECT * FROM refresh_log ORDER BY id"):
        target.execute(
            """
            INSERT INTO refresh_runs (
                source, scope, status, games_checked, games_processed,
                facts_loaded, message, created_at, completed_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                row["refresh_type"] or "legacy",
                row["refresh_date"] or "global",
                row["status"] or "unknown",
                _as_int(row["games_checked"]),
                _as_int(row["games_processed"]),
                _as_int(row["plate_appearances_loaded"]) + _as_int(row["pitcher_logs_loaded"]),
                row["message"],
                row["created_at"],
                row["created_at"],
            ),
        )
    return quarantined


def _drop_bulk_load_indexes(target: Cursor[Any]) -> None:
    target.execute(
        "ALTER TABLE batter_pitcher_game_logs DROP CONSTRAINT uq_bvp_game_batter_pitcher"
    )
    target.execute("ALTER TABLE pitcher_game_logs DROP CONSTRAINT uq_pitcher_game_pitcher")
    for index in (
        "ix_bvp_batter_pitcher_date",
        "ix_bvp_season_batter_date",
        "ix_pitcher_history",
        "ix_pitcher_opponent_date",
    ):
        target.execute(f'DROP INDEX "{index}"')


def _restore_bulk_load_indexes(target: Cursor[Any]) -> None:
    target.execute(
        "ALTER TABLE batter_pitcher_game_logs ADD CONSTRAINT "
        "uq_bvp_game_batter_pitcher UNIQUE (game_id, batter_id, pitcher_id)"
    )
    target.execute(
        "ALTER TABLE pitcher_game_logs ADD CONSTRAINT "
        "uq_pitcher_game_pitcher UNIQUE (game_id, pitcher_id)"
    )
    target.execute(
        "CREATE INDEX ix_bvp_batter_pitcher_date ON batter_pitcher_game_logs "
        "(batter_id, pitcher_id, game_date)"
    )
    target.execute(
        "CREATE INDEX ix_bvp_season_batter_date ON batter_pitcher_game_logs "
        "(season, batter_id, game_date)"
    )
    target.execute(
        "CREATE INDEX ix_pitcher_history ON pitcher_game_logs (season, pitcher_id, game_date)"
    )
    target.execute(
        "CREATE INDEX ix_pitcher_opponent_date ON pitcher_game_logs "
        "(pitcher_id, opponent_team_id, game_date)"
    )


TARGET_COUNT_TABLES = (
    "games",
    "players",
    "batter_pitcher_game_logs",
    "batter_pitcher_summaries",
    "pitcher_game_logs",
    "pitcher_season_summaries",
    "live_game_contacts",
    "bullpen_projection_items",
    "refresh_runs",
)


def _reconcile(
    target: Cursor[Any],
    audit: SnapshotAudit,
    quarantined: dict[str, int],
) -> tuple[dict[str, int], dict[str, int], dict[str, int]]:
    target_counts: dict[str, int] = {}
    for table in TARGET_COUNT_TABLES:
        target.execute(f'SELECT COUNT(*) FROM "{table}"')
        target_counts[table] = int(_target_scalar(target))
    expected = {
        "games": audit.table_counts["games"],
        "players": audit.table_counts["players"],
        "batter_pitcher_game_logs": audit.table_counts["batter_pitcher_game_logs"],
        "pitcher_game_logs": audit.table_counts["pitcher_game_logs"],
        "live_game_contacts": (
            audit.table_counts["live_game_contacts"]
            - quarantined["live_game_contacts_without_game"]
        ),
        "bullpen_projection_items": (
            audit.table_counts["daily_bullpen_projections"]
            - quarantined["bullpen_projections_without_game"]
        ),
        "refresh_runs": audit.table_counts["refresh_log"],
    }
    mismatches = {
        table: target_counts[table] - count
        for table, count in expected.items()
        if target_counts[table] != count
    }
    if mismatches:
        raise MigrationError(f"Target row-count reconciliation failed: {mismatches}")
    orphan_sql = {
        "bvp_games": """
            SELECT COUNT(*) FROM batter_pitcher_game_logs l
            LEFT JOIN games g ON g.id=l.game_id WHERE g.id IS NULL
        """,
        "bvp_players": """
            SELECT COUNT(*) FROM batter_pitcher_game_logs l
            LEFT JOIN players b ON b.id=l.batter_id
            LEFT JOIN players p ON p.id=l.pitcher_id
            WHERE b.id IS NULL OR p.id IS NULL
        """,
        "pitcher_games": """
            SELECT COUNT(*) FROM pitcher_game_logs l
            LEFT JOIN games g ON g.id=l.game_id WHERE g.id IS NULL
        """,
    }
    target_orphans = {}
    for name, sql in orphan_sql.items():
        target.execute(sql)
        target_orphans[name] = int(_target_scalar(target))
    if any(target_orphans.values()):
        raise MigrationError(f"Target contains orphaned facts: {target_orphans}")
    total_queries = {
        "bvp_pa": "SELECT COALESCE(SUM(pa), 0) FROM batter_pitcher_game_logs",
        "bvp_ab": "SELECT COALESCE(SUM(ab), 0) FROM batter_pitcher_game_logs",
        "bvp_hits": "SELECT COALESCE(SUM(hits), 0) FROM batter_pitcher_game_logs",
        "bvp_strikeouts": "SELECT COALESCE(SUM(strikeouts), 0) FROM batter_pitcher_game_logs",
        "bvp_home_runs": "SELECT COALESCE(SUM(home_runs), 0) FROM batter_pitcher_game_logs",
        "bvp_total_bases": "SELECT COALESCE(SUM(total_bases), 0) FROM batter_pitcher_game_logs",
        "pitcher_innings_outs": "SELECT COALESCE(SUM(innings_outs), 0) FROM pitcher_game_logs",
        "pitcher_batters_faced": "SELECT COALESCE(SUM(batters_faced), 0) FROM pitcher_game_logs",
        "pitcher_hits": "SELECT COALESCE(SUM(hits), 0) FROM pitcher_game_logs",
        "pitcher_walks": "SELECT COALESCE(SUM(walks), 0) FROM pitcher_game_logs",
        "pitcher_strikeouts": "SELECT COALESCE(SUM(strikeouts), 0) FROM pitcher_game_logs",
        "pitcher_earned_runs": "SELECT COALESCE(SUM(earned_runs), 0) FROM pitcher_game_logs",
    }
    target_totals = {}
    for name, sql in total_queries.items():
        target.execute(sql)
        target_totals[name] = int(_target_scalar(target))
    if target_totals != audit.fact_totals:
        raise MigrationError("Target aggregate-total reconciliation failed")
    target.execute("SELECT source, COUNT(*) FROM games GROUP BY source ORDER BY source")
    target_sources = {str(source): int(count) for source, count in target.fetchall()}
    if target_sources != audit.game_source_counts:
        raise MigrationError("Target game-source reconciliation failed")
    target.execute("SELECT MIN(game_date), MAX(game_date), MIN(season), MAX(season) FROM games")
    target_range = target.fetchone()
    expected_range = (
        audit.min_game_date,
        audit.max_game_date,
        audit.min_season,
        audit.max_season,
    )
    if (
        target_range is None
        or tuple(str(value) if index < 2 else value for index, value in enumerate(target_range))
        != expected_range
    ):
        raise MigrationError("Target game-range reconciliation failed")
    return target_counts, target_orphans, target_totals


def migrate_snapshot(
    snapshot_path: Path,
    database_url: str,
    *,
    chunk_size: int = 10_000,
) -> MigrationReport:
    audit = audit_snapshot(snapshot_path)
    now = datetime.now(UTC)
    with (
        open_snapshot(snapshot_path) as source,
        psycopg.connect(database_url) as target_connection,
        target_connection.cursor() as target,
    ):
        target.execute("SELECT COUNT(*) FROM games")
        if int(_target_scalar(target)):
            raise MigrationError("Shadow target is not empty; refusing a destructive reload")
        teams = _team_catalog(source)
        target.executemany(
            """INSERT INTO teams
                   (source_key, abbreviation, provider_team_id, name,
                    source_version, updated_at)
                   VALUES (%s, NULL, %s, %s, %s, %s)""",
            [
                (key, provider, name, audit.generation, now)
                for key, (name, provider) in teams.items()
            ],
        )
        for row in source.execute("SELECT * FROM players ORDER BY player_id"):
            target.execute(
                """INSERT INTO players (
                           provider_player_id, retrosheet_player_id, name,
                           active_status, source_updated_at
                       )
                       VALUES (%s, %s, %s, %s, %s)""",
                (
                    row["player_id"],
                    row["retro_id"],
                    row["player_name"],
                    row["active_status"] or "unknown",
                    row["updated_at"],
                ),
            )
        team_map = _target_map(target, "SELECT source_key, id FROM teams")
        team_provider_map = _target_map(
            target, "SELECT provider_team_id, id FROM teams WHERE provider_team_id IS NOT NULL"
        )
        player_map = _target_map(target, "SELECT provider_player_id, id FROM players")
        for row in source.execute("SELECT * FROM games ORDER BY game_date, game_pk"):
            source_game_id, mlb_game_pk = canonical_game_identity(row)
            target.execute(
                """
                    INSERT INTO games (
                        source_game_id, mlb_game_pk, retrosheet_game_id,
                        legacy_game_pk, source, source_version, game_date, season,
                        away_team_id, home_team_id, away_probable_pitcher_id,
                        home_probable_pitcher_id, game_status, source_updated_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                (
                    source_game_id,
                    mlb_game_pk,
                    row["retrosheet_game_id"],
                    row["game_pk"],
                    row["source"],
                    audit.generation,
                    row["game_date"],
                    row["season"],
                    team_map[str(row["away_team"]).upper()],
                    team_map[str(row["home_team"]).upper()],
                    player_map.get(int(row["away_probable_pitcher_id"]))
                    if row["away_probable_pitcher_id"]
                    else None,
                    player_map.get(int(row["home_probable_pitcher_id"]))
                    if row["home_probable_pitcher_id"]
                    else None,
                    row["game_status"],
                    row["updated_at"],
                ),
            )
        game_map = _target_map(target, "SELECT legacy_game_pk, id FROM games")
        _drop_bulk_load_indexes(target)
        _copy_bvp(source, target, game_map, player_map, team_map, chunk_size=chunk_size)
        _copy_pitchers(source, target, game_map, player_map, team_map, chunk_size=chunk_size)
        _rebuild_summaries(target, audit.generation)
        quarantined = _load_small_tables(
            source, target, game_map, player_map, team_provider_map, audit.generation
        )
        if quarantined != audit.quarantined_counts:
            raise MigrationError(
                f"Quarantine reconciliation failed: {quarantined} != {audit.quarantined_counts}"
            )
        _restore_bulk_load_indexes(target)
        target.execute(
            """
                INSERT INTO source_artifacts (
                    source, generation, uri, sha256, size_bytes, fetched_at,
                    source_version, inventory
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
            (
                "legacy-sqlite",
                audit.generation,
                snapshot_path.resolve().as_uri(),
                audit.sha256,
                audit.size_bytes,
                now,
                None,
                Jsonb(asdict(audit)),
            ),
        )
        target.execute(
            """
                INSERT INTO processing_checkpoints
                    (source, scope, watermark, source_version, updated_at)
                VALUES ('legacy-sqlite', 'games', %s, %s, %s)
                """,
            (audit.max_game_date or "", audit.generation, now),
        )
        target.execute(
            """
                INSERT INTO data_source_status
                    (source, watermark, freshness_status, last_success_at, detail)
                VALUES ('legacy-sqlite', %s, 'snapshot', %s, %s)
                """,
            (audit.max_game_date, now, f"Immutable generation {audit.generation}"),
        )
        target_counts, target_orphans, target_totals = _reconcile(target, audit, quarantined)
    return MigrationReport(
        audit,
        target_counts,
        target_orphans,
        target_totals,
        datetime.now(UTC).isoformat(),
    )


def validate_shadow(snapshot_path: Path, database_url: str) -> MigrationReport:
    audit = audit_snapshot(snapshot_path)
    with psycopg.connect(database_url) as connection, connection.cursor() as target:
        target_counts, target_orphans, target_totals = _reconcile(
            target, audit, audit.quarantined_counts
        )
    return MigrationReport(
        audit,
        target_counts,
        target_orphans,
        target_totals,
        datetime.now(UTC).isoformat(),
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("snapshot", type=Path)
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--chunk-size", type=int, default=10_000)
    parser.add_argument("--audit-only", action="store_true")
    parser.add_argument("--validate-only", action="store_true")
    parser.add_argument("--manifest", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result: SnapshotAudit | MigrationReport
    if args.audit_only and args.validate_only:
        raise MigrationError("Choose only one of --audit-only or --validate-only")
    if args.audit_only:
        result = audit_snapshot(args.snapshot)
    elif args.validate_only:
        result = validate_shadow(args.snapshot, args.database_url)
    else:
        result = migrate_snapshot(args.snapshot, args.database_url, chunk_size=args.chunk_size)
    payload = json.dumps(asdict(result), indent=2, sort_keys=True)
    if args.manifest:
        args.manifest.write_text(f"{payload}\n", encoding="utf-8")
    print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
