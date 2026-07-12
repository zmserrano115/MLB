from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from all_rise.migration.sqlite_snapshot import (
    MigrationError,
    audit_snapshot,
    canonical_game_identity,
    parse_workload_range,
)
from all_rise.models import Base


def create_audit_snapshot(path: Path, *, game_id: str = "mlb:123") -> None:
    with sqlite3.connect(path) as connection:
        connection.executescript(
            """
            CREATE TABLE games (
                game_pk INTEGER PRIMARY KEY,
                game_id TEXT,
                source TEXT,
                game_date TEXT,
                season INTEGER
            );
            CREATE TABLE players (player_id INTEGER PRIMARY KEY);
            CREATE TABLE batter_pitcher_game_logs (
                game_pk INTEGER,
                batter_id INTEGER,
                pitcher_id INTEGER,
                PA INTEGER, AB INTEGER, H INTEGER, SO INTEGER, HR INTEGER, TB INTEGER
            );
            CREATE TABLE pitcher_game_logs (
                game_pk INTEGER,
                IP_outs INTEGER, BF INTEGER, H INTEGER, BB INTEGER, SO INTEGER, ER INTEGER
            );
            CREATE TABLE live_game_contacts (game_pk INTEGER);
            CREATE TABLE daily_bullpen_projections (game_pk INTEGER);
            CREATE TABLE refresh_log (id INTEGER);
            CREATE INDEX ix_fixture_games_date ON games(game_date);
            """
        )
        connection.execute(
            "INSERT INTO games VALUES (123, ?, 'mlb_statsapi', '2026-07-12', 2026)",
            (game_id,),
        )
        connection.execute("INSERT INTO players VALUES (10)")
        connection.execute("INSERT INTO players VALUES (20)")
        connection.execute(
            "INSERT INTO batter_pitcher_game_logs VALUES (123, 10, 20, 4, 3, 1, 1, 0, 1)"
        )
        connection.execute("INSERT INTO pitcher_game_logs VALUES (123, 18, 7, 2, 1, 3, 1)")


def test_snapshot_audit_records_integrity_inventory_and_ranges(tmp_path: Path) -> None:
    path = tmp_path / "snapshot.db"
    create_audit_snapshot(path)

    audit = audit_snapshot(path)

    assert audit.quick_check == "ok"
    assert len(audit.sha256) == 64
    assert audit.table_counts["games"] == 1
    assert audit.game_source_counts == {"mlb_statsapi": 1}
    assert audit.fact_totals["bvp_pa"] == 4
    assert audit.fact_totals["pitcher_innings_outs"] == 18
    assert audit.min_game_date == "2026-07-12"
    assert audit.max_season == 2026
    assert "ix_fixture_games_date" in audit.index_names
    assert not any(audit.orphan_counts.values())
    assert not any(audit.quarantined_counts.values())


def test_snapshot_audit_rejects_noncanonical_ids(tmp_path: Path) -> None:
    path = tmp_path / "snapshot.db"
    create_audit_snapshot(path, game_id="123")

    with pytest.raises(MigrationError, match="referential audit"):
        audit_snapshot(path)


def test_snapshot_audit_rejects_uncheckpointed_wal(tmp_path: Path) -> None:
    path = tmp_path / "snapshot.db"
    create_audit_snapshot(path)
    Path(f"{path}-wal").write_bytes(b"pending")

    with pytest.raises(MigrationError, match="non-empty WAL"):
        audit_snapshot(path)


@pytest.mark.parametrize(
    ("row", "expected"),
    [
        ({"game_pk": 123, "game_id": "mlb:123"}, ("mlb:123", 123)),
        (
            {"game_pk": 9_000_000_000_000_001, "game_id": "retro:COL202607120"},
            ("retro:COL202607120", None),
        ),
    ],
)
def test_canonical_game_identity_keeps_api_ids_string_safe(row, expected) -> None:
    assert canonical_game_identity(row) == expected


def test_workload_range_normalization() -> None:
    assert parse_workload_range("3-6") == (3, 6)
    assert parse_workload_range("4 to 7 batters") == (4, 7)
    assert parse_workload_range(None) == (None, None)


def test_model_metadata_contains_normalized_phase4_boundary() -> None:
    assert {
        "teams",
        "players",
        "games",
        "batter_pitcher_game_logs",
        "batter_pitcher_summaries",
        "pitcher_game_logs",
        "pitcher_season_summaries",
        "live_game_contacts",
        "bullpen_projection_runs",
        "bullpen_projection_items",
        "refresh_runs",
        "processing_checkpoints",
        "data_source_status",
        "source_artifacts",
    } == set(Base.metadata.tables)
    assert Base.metadata.tables["games"].c.source_game_id.type.length == 80
    assert Base.metadata.tables["games"].c.legacy_game_pk.type.python_type is int
