import gzip
import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from src import database


class RawBytes(io.BytesIO):
    pass


class DatabaseTests(unittest.TestCase):
    def setUp(self):
        self.environment = patch.dict(
            os.environ,
            {
                "TURSO_DATABASE_URL": "",
                "TURSO_AUTH_TOKEN": "",
                "TURSO_READ_ONLY": "",
                "TURSO_DATA_VERSION": "",
            },
        )
        self.environment.start()
        self.original_db_path = database.DB_PATH
        self.original_initialized_path = database._INITIALIZED_PATH
        self.temp_dir = tempfile.TemporaryDirectory()
        database.DB_PATH = Path(self.temp_dir.name) / "test.db"
        database._INITIALIZED_PATH = None
        database.init_database()

    def tearDown(self):
        database.DB_PATH = self.original_db_path
        database._INITIALIZED_PATH = self.original_initialized_path
        self.temp_dir.cleanup()
        self.environment.stop()

    def test_turso_connection_preserves_sqlite_row_access(self):
        class FakeCursor:
            description = (("player_id", None), ("player_name", None))

            def __init__(self):
                self.rows = [(42, "Jackie Robinson")]

            def fetchone(self):
                return self.rows[0]

            def fetchall(self):
                return list(self.rows)

            def __iter__(self):
                return iter(self.rows)

        class FakeConnection:
            def execute(self, sql, parameters=None):
                return FakeCursor()

            def close(self):
                return None

        with patch.dict(
            os.environ,
            {
                "TURSO_DATABASE_URL": "libsql://all-rise.example.turso.io",
                "TURSO_AUTH_TOKEN": "secret-token",
            },
        ), patch("src.database._connect_turso", return_value=FakeConnection()):
            with database.read_connection() as conn:
                row = conn.execute(
                    "SELECT player_id, player_name FROM players"
                ).fetchone()

        self.assertEqual(row[0], 42)
        self.assertEqual(row["player_name"], "Jackie Robinson")
        self.assertEqual(
            dict(row),
            {"player_id": 42, "player_name": "Jackie Robinson"},
        )

    def test_turso_http_connection_decodes_rows_and_binds_parameters(self):
        calls = []

        class FakeResponse:
            def __init__(self, body):
                self.body = body

            def raise_for_status(self):
                return None

            def json(self):
                return self.body

        class FakeSession:
            def post(self, url, headers, json, timeout):
                calls.append((url, headers, json, timeout))
                request = json["requests"][0]
                if request["type"] == "close":
                    return FakeResponse(
                        {
                            "baton": None,
                            "results": [
                                {"type": "ok", "response": {"type": "close"}}
                            ],
                        }
                    )
                return FakeResponse(
                    {
                        "baton": "connection-baton",
                        "results": [
                            {
                                "type": "ok",
                                "response": {
                                    "type": "execute",
                                    "result": {
                                        "cols": [
                                            {"name": "player_id"},
                                            {"name": "player_name"},
                                        ],
                                        "rows": [
                                            [
                                                {"type": "integer", "value": "42"},
                                                {
                                                    "type": "text",
                                                    "value": "Jackie Robinson",
                                                },
                                            ]
                                        ],
                                    },
                                },
                            }
                        ],
                    }
                )

            def close(self):
                return None

        with patch("src.database.requests.Session", return_value=FakeSession()):
            connection = database._RemoteConnection(
                database._connect_turso(
                    "libsql://all-rise.example.turso.io",
                    "secret-token",
                )
            )
            row = connection.execute(
                "SELECT player_id, player_name FROM players WHERE player_id = ?",
                (42,),
            ).fetchone()
            connection.close()

        self.assertEqual(row["player_id"], 42)
        self.assertEqual(row[1], "Jackie Robinson")
        self.assertEqual(calls[0][0], "https://all-rise.example.turso.io/v2/pipeline")
        self.assertEqual(
            calls[0][2]["requests"][0]["stmt"]["args"],
            [{"type": "integer", "value": "42"}],
        )
        self.assertEqual(calls[1][2]["requests"], [{"type": "close"}])

    def test_turso_http_connection_exposes_transaction_methods(self):
        connection = database._HttpConnection(
            "libsql://all-rise.example.turso.io",
            "secret-token",
        )
        with patch.object(connection, "execute") as execute:
            connection.commit()
            connection.rollback()

        self.assertEqual(
            [call.args[0] for call in execute.call_args_list],
            ["COMMIT", "ROLLBACK"],
        )

    def test_turso_http_encodes_float_arguments_as_json_numbers(self):
        self.assertEqual(
            database._encode_http_value(12.5),
            {"type": "float", "value": 12.5},
        )
        self.assertEqual(
            database._encode_http_value(float("nan")),
            {"type": "null"},
        )

    def test_turso_http_rollback_ignores_absent_transaction(self):
        connection = database._HttpConnection(
            "libsql://all-rise.example.turso.io",
            "secret-token",
        )
        with patch.object(
            connection,
            "execute",
            side_effect=RuntimeError("cannot rollback - no transaction is active"),
        ):
            connection.rollback()

        with patch.object(
            connection,
            "execute",
            side_effect=RuntimeError("network failure"),
        ):
            with self.assertRaisesRegex(RuntimeError, "network failure"):
                connection.rollback()

    def test_turso_http_transaction_batches_work_before_commit(self):
        connection = database._HttpConnection(
            "libsql://all-rise.example.turso.io",
            "secret-token",
        )
        ok = {
            "type": "ok",
            "response": {"type": "execute", "result": {}},
        }
        with patch.object(
            connection,
            "_pipeline",
            side_effect=[[ok, ok], [ok]],
        ) as pipeline:
            connection.execute("BEGIN")
            connection.execute("INSERT INTO players (player_id) VALUES (?)", (42,))
            pipeline.assert_not_called()
            connection.commit()

        first_pipeline = pipeline.call_args_list[0].args[0]
        self.assertEqual(first_pipeline[0]["stmt"]["sql"], "BEGIN")
        self.assertEqual(
            first_pipeline[1]["stmt"]["args"],
            [{"type": "integer", "value": "42"}],
        )
        self.assertEqual(
            pipeline.call_args_list[1].args[0][0]["stmt"]["sql"],
            "COMMIT",
        )

    def test_turso_skips_local_bootstrap_and_schema_writes(self):
        statements = []

        class FakeCursor:
            description = (("ready", None),)

            def fetchone(self):
                return (1,)

        class FakeConnection:
            def execute(self, sql, parameters=None):
                statements.append(sql)
                return FakeCursor()

            def close(self):
                return None

        database._INITIALIZED_PATH = None
        with patch.dict(
            os.environ,
            {
                "TURSO_DATABASE_URL": "libsql://all-rise.example.turso.io",
                "TURSO_AUTH_TOKEN": "secret-token",
            },
        ), patch("src.database._connect_turso", return_value=FakeConnection()), patch(
            "src.database._bootstrap_database"
        ) as bootstrap:
            database.bootstrap_database()
            database.ensure_database()

        bootstrap.assert_not_called()
        self.assertEqual(statements, ["SELECT 1 FROM games LIMIT 1"])
        self.assertTrue(str(database._INITIALIZED_PATH).startswith("turso:"))

    def test_turso_cache_key_is_versioned_without_exposing_credentials(self):
        with patch.dict(
            os.environ,
            {
                "TURSO_DATABASE_URL": "libsql://all-rise.example.turso.io",
                "TURSO_AUTH_TOKEN": "do-not-leak",
                "TURSO_DATA_VERSION": "2026-07-15",
            },
        ):
            cache_key = database.db_cache_key()

        self.assertIn("2026-07-15", cache_key)
        self.assertNotIn("do-not-leak", repr(cache_key))
        self.assertNotIn("all-rise.example.turso.io", repr(cache_key))

    def test_turso_is_read_only_by_default(self):
        with patch.dict(
            os.environ,
            {
                "TURSO_DATABASE_URL": "libsql://all-rise.example.turso.io",
                "TURSO_AUTH_TOKEN": "read-only-token",
                "TURSO_READ_ONLY": "",
            },
        ):
            self.assertFalse(database.database_writes_enabled())
            self.assertEqual(
                database.save_live_game_contacts(
                    1,
                    [{"play_index": 1, "hit_data": {"x": 10, "y": 20}}],
                ),
                0,
            )

    def test_turso_completed_game_refreshes_only_touched_summaries(self):
        game = {
            "game_pk": 321,
            "game_date": "2026-07-14",
            "season": 2026,
            "away_team": "New York Yankees",
            "home_team": "Boston Red Sox",
            "game_status": "Final",
        }
        batter_pitcher_log = {
            "game_pk": 321,
            "game_date": "2026-07-14",
            "season": 2026,
            "batter_id": 10,
            "pitcher_id": 20,
            "PA": 1,
            "AB": 1,
            "H": 1,
            "doubles": 0,
            "triples": 0,
            "BB": 0,
            "HBP": 0,
            "SO": 0,
            "HR": 1,
            "RBI": 1,
            "SF": 0,
            "TB": 4,
        }
        batter_pitch_type_log = {
            **batter_pitcher_log,
            "batting_team": "New York Yankees",
            "pitcher_hand": "R",
            "pitch_code": "FF",
            "singles": 0,
        }
        pitcher_pitch_type_log = {
            "game_pk": 321,
            "game_date": "2026-07-14",
            "season": 2026,
            "pitcher_id": 20,
            "team": "Boston Red Sox",
            "opponent": "New York Yankees",
            "pitch_code": "FF",
            "pitch_count": 10,
            "total_speed": 960.0,
            "measured_pitches": 10,
        }
        pitcher_log = {
            "game_pk": 321,
            "game_date": "2026-07-14",
            "season": 2026,
            "pitcher_id": 20,
            "pitcher_name": "Test Pitcher",
            "is_starter": 1,
            "IP_outs": 18,
            "IP": 6.0,
            "pitch_count": 90,
            "BF": 22,
            "H": 4,
            "BB": 1,
            "HBP": 0,
            "SO": 8,
            "HR": 1,
            "R": 1,
            "ER": 1,
        }

        with patch("src.database.using_turso", return_value=True), patch(
            "src.database.database_writes_enabled", return_value=True
        ):
            database.save_completed_game(
                game=game,
                players={10: "Test Batter", 20: "Test Pitcher"},
                batter_pitcher_logs=[batter_pitcher_log],
                batter_pitch_type_logs=[batter_pitch_type_log],
                pitcher_pitch_type_logs=[pitcher_pitch_type_log],
                pitch_types={"FF": "Four-Seam Fastball"},
                pitcher_logs=[pitcher_log],
                plate_appearances_loaded=1,
            )

        self.assertEqual(
            database.get_batter_vs_pitcher_stats_from_db(10, 20)["HR"],
            1,
        )
        self.assertEqual(
            database.get_batter_pitch_type_stats_from_db(10, 2026, "R")[0]["HR"],
            1,
        )
        self.assertEqual(
            database.get_pitcher_pitch_type_stats_from_db(20, 2026)[0]["COUNT"],
            10,
        )
        self.assertEqual(database.get_pitcher_stats_from_db(2026, 20)["SO"], 8)

    def test_download_database_expands_gzip_release_asset(self):
        payload = b"SQLite format 3\x00" + (b"database-bytes" * 10)
        compressed = gzip.compress(payload)
        target = Path(self.temp_dir.name) / "downloaded.db"
        response = Mock()
        response.raw = RawBytes(compressed)
        response.raise_for_status.return_value = None
        response.close.return_value = None

        with patch(
            "src.database.http_get",
            return_value=response,
        ):
            database._download_database(
                "https://example.test/mlb.db.gz",
                target,
            )

        self.assertEqual(target.read_bytes(), payload)

    def test_download_database_rejects_sha256_mismatch(self):
        payload = b"SQLite format 3\x00" + (b"database-bytes" * 10)
        response = Mock()
        response.raw = RawBytes(payload)
        response.raise_for_status.return_value = None
        response.close.return_value = None
        target = Path(self.temp_dir.name) / "downloaded.db"

        with patch(
            "src.database.http_get",
            return_value=response,
        ):
            with self.assertRaisesRegex(ValueError, "SHA256"):
                database._download_database(
                    "https://example.test/mlb.db",
                    target,
                    expected_sha256="0" * 64,
                )

    def test_db_cache_key_reflects_database_identity(self):
        first_key = database.db_cache_key()

        with database.transaction() as conn:
            conn.execute(
                """
                INSERT INTO players (player_id, player_name, updated_at)
                VALUES (?, ?, ?)
                """,
                (999, "Cache Key Player", database.now_text()),
            )

        second_key = database.db_cache_key()
        self.assertNotEqual(first_key, second_key)
        self.assertEqual(second_key[-1], database.SCHEMA_VERSION)

    def test_requested_read_indexes_are_created(self):
        expected_indexes = {
            "idx_bpg_logs_batter_pitcher_date_game",
            "idx_pitcher_logs_pitcher_opponent_date_game",
            "idx_pitcher_logs_season_pitcher_date_game",
            "idx_batter_pitch_type_stats_batch",
            "idx_pitcher_pitch_type_stats_batch",
            "idx_pitch_level_batter_pitcher_date",
            "idx_pitch_level_pitcher_type_date",
            "idx_pitch_level_batter_type_date",
            "idx_pitch_level_game_pitch",
            "idx_daily_bullpen_team_date",
            "idx_daily_bullpen_game_pitcher",
        }
        with database.read_connection() as conn:
            indexes = {
                row["name"]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'index'"
                )
            }
        self.assertTrue(expected_indexes.issubset(indexes))

    def test_advanced_hvp_tables_are_created(self):
        expected_tables = {
            "pitch_level_events",
            "plate_appearance_sequences",
            "bvp_pitch_type_stats",
            "daily_bullpen_projections",
        }
        with database.read_connection() as conn:
            table_names = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }
            user_version = conn.execute("PRAGMA user_version").fetchone()[0]
        self.assertTrue(expected_tables.issubset(table_names))
        self.assertEqual(user_version, database.SCHEMA_VERSION)

    def test_pitch_level_events_and_sequences_upsert(self):
        event = {
            "game_pk": 1,
            "game_date": "2026-07-01",
            "season": 2026,
            "at_bat_number": 4,
            "pitch_number": 1,
            "batter_id": 10,
            "pitcher_id": 20,
            "pitch_type": "FF",
            "pitch_name": "Four-Seam Fastball",
            "release_speed": 96.2,
        }
        self.assertEqual(database.save_pitch_level_events([event]), 1)
        self.assertEqual(
            database.save_pitch_level_events([{**event, "release_speed": 97.0}]),
            1,
        )
        rows = database.get_pitch_level_events_for_matchup(10, 20)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["release_speed"], 97.0)

        sequence = {
            "game_pk": 1,
            "game_date": "2026-07-01",
            "season": 2026,
            "at_bat_number": 4,
            "batter_id": 10,
            "pitcher_id": 20,
            "pitch_count": 1,
            "pitch_sequence": "FF",
            "pa_result": "single",
        }
        database.save_plate_appearance_sequences([sequence])
        sequence_rows = database.get_plate_appearance_sequences_for_matchup(10, 20)
        self.assertEqual(len(sequence_rows), 1)
        self.assertEqual(sequence_rows[0]["pitch_sequence"], "FF")

    def test_daily_bullpen_projection_cache_upserts(self):
        projection = {
            "game_date": "2026-07-11",
            "game_pk": 99,
            "team_id": 147,
            "pitcher_id": 20,
            "projected_role": "Closer",
            "availability_score": 82.0,
            "availability_label": "Available",
            "appearance_probability": 0.3,
            "expected_batters_faced_range": "3-4",
            "recent_workload": "fresh",
            "projection_reason": "fresh recent workload",
            "projection_timestamp": "2026-07-11T12:00:00Z",
        }
        database.save_daily_bullpen_projections([projection])
        database.save_daily_bullpen_projections(
            [{**projection, "availability_score": 74.0, "availability_label": "Likely"}]
        )
        rows = database.get_daily_bullpen_projection_from_db(99, 147)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["availability_label"], "Likely")

    def test_live_game_contacts_are_persisted_and_upserted(self):
        first_play = {
            "play_index": 4,
            "inning": 1,
            "half_inning": "top",
            "batting_side": "away",
            "batting_team": "New York Yankees",
            "batter": {"player_id": 10, "name": "Test Batter"},
            "pitcher": {"player_id": 20, "name": "Test Pitcher"},
            "result_type": "single",
            "result_label": "Single",
            "description": "Test Batter singles on a line drive.",
            "runs_scored": 0,
            "away_score": 0,
            "home_score": 0,
            "hit_data": {
                "x": 92.5,
                "y": 118.0,
                "launch_speed": 101.2,
                "launch_angle": 14.0,
                "distance": 210.0,
                "trajectory": "line_drive",
                "hardness": "hard",
                "location": 8,
            },
        }
        second_play = {
            **first_play,
            "play_index": 8,
            "result_type": "field_out",
            "result_label": "Out",
            "description": "Test Batter lines out.",
            "hit_data": {**first_play["hit_data"], "x": 80.0, "y": 140.0},
        }

        saved_count = database.save_live_game_contacts(999, [first_play, second_play])
        self.assertEqual(saved_count, 2)
        loaded = database.load_live_game_contacts(999)
        self.assertEqual(len(loaded), 2)
        self.assertEqual(loaded[0]["hit_data"]["x"], 92.5)

        updated_first_play = {
            **first_play,
            "description": "Updated single description.",
        }
        database.save_live_game_contacts(999, [updated_first_play])
        loaded = database.load_live_game_contacts(999)
        self.assertEqual(len(loaded), 2)
        self.assertEqual(loaded[0]["description"], "Updated single description.")

    def test_completed_game_rebuilds_matchup_and_pitcher_summaries(self):
        game = {
            "game_pk": 123,
            "game_date": "2026-06-01",
            "season": 2026,
            "away_team": "New York Yankees",
            "home_team": "Boston Red Sox",
            "game_status": "Final",
        }
        bvp_log = {
            "game_pk": 123,
            "game_date": "2026-06-01",
            "season": 2026,
            "batter_id": 10,
            "pitcher_id": 20,
            "batting_team": "New York Yankees",
            "pitching_team": "Boston Red Sox",
            "PA": 2,
            "AB": 1,
            "H": 1,
            "doubles": 1,
            "triples": 0,
            "BB": 1,
            "HBP": 0,
            "SO": 0,
            "HR": 0,
            "RBI": 1,
            "SF": 0,
            "TB": 2,
        }
        pitcher_log = {
            "game_pk": 123,
            "game_date": "2026-06-01",
            "season": 2026,
            "pitcher_id": 20,
            "pitcher_name": "Test Pitcher",
            "team": "Boston Red Sox",
            "opponent": "New York Yankees",
            "is_starter": 1,
            "IP_outs": 16,
            "IP": 5.1,
            "pitch_count": 88,
            "BF": 22,
            "H": 5,
            "BB": 2,
            "HBP": 0,
            "SO": 7,
            "HR": 1,
            "R": 2,
            "ER": 2,
        }
        pitch_type_log = {
            "game_pk": 123,
            "game_date": "2026-06-01",
            "season": 2026,
            "batter_id": 10,
            "batting_team": "New York Yankees",
            "pitcher_hand": "L",
            "pitch_code": "FF",
            "PA": 1,
            "AB": 1,
            "H": 1,
            "singles": 0,
            "doubles": 1,
            "triples": 0,
            "BB": 0,
            "HBP": 0,
            "SO": 0,
            "HR": 0,
            "SF": 0,
            "TB": 2,
        }
        pitcher_pitch_type_log = {
            "game_pk": 123,
            "game_date": "2026-06-01",
            "season": 2026,
            "pitcher_id": 20,
            "team": "Boston Red Sox",
            "opponent": "New York Yankees",
            "pitch_code": "FF",
            "pitch_count": 10,
            "total_speed": 965.0,
            "measured_pitches": 10,
        }

        database.save_completed_game(
            game=game,
            players={10: "Test Batter", 20: "Test Pitcher"},
            batter_pitcher_logs=[bvp_log],
            batter_pitch_type_logs=[pitch_type_log],
            pitcher_pitch_type_logs=[pitcher_pitch_type_log],
            pitch_types={"FF": "Four-Seam Fastball"},
            pitcher_logs=[pitcher_log],
            plate_appearances_loaded=2,
        )
        database.rebuild_all_summary_stats()

        stats = database.get_batter_vs_pitcher_stats_from_db(10, 20)
        self.assertEqual(stats["PA"], 2)
        self.assertEqual(stats["2B"], 1)
        self.assertEqual(stats["OPS"], 3.000)

        batch_stats = database.get_batter_vs_pitcher_stats_batch_from_db(
            [(10, 20), (10, 999)]
        )
        self.assertEqual(batch_stats[(10, 20)]["PA"], 2)
        self.assertEqual(batch_stats[(10, 999)]["matchup_grade"], "No History")

        game_logs = database.get_batter_vs_pitcher_game_logs_from_db(10, 20)
        self.assertEqual(len(game_logs), 1)
        self.assertEqual(game_logs[0]["home_away"], "Away")
        self.assertEqual(game_logs[0]["TB"], 2)

        batter_season_logs = database.get_batter_season_game_logs_from_db(
            10,
            2026,
        )
        self.assertEqual(len(batter_season_logs), 1)
        self.assertEqual(batter_season_logs[0]["opponent"], "Boston Red Sox")
        self.assertEqual(batter_season_logs[0]["OPS"], 3.000)

        pitcher_stats = database.get_pitcher_stats_from_db(2026, 20)
        self.assertEqual(pitcher_stats["starts"], 1)
        self.assertEqual(pitcher_stats["IP"], 5.1)
        self.assertEqual(pitcher_stats["projected_pitch_count"], 88)

        pitch_type_stats = database.get_batter_pitch_type_stats_from_db(
            10,
            2026,
            "L",
        )
        self.assertEqual(len(pitch_type_stats), 1)
        self.assertEqual(pitch_type_stats[0]["PITCH"], "Four-Seam Fastball")
        self.assertEqual(pitch_type_stats[0]["AB"], 1)
        self.assertEqual(pitch_type_stats[0]["H"], 1)
        self.assertEqual(pitch_type_stats[0]["2B"], 1)
        self.assertEqual(pitch_type_stats[0]["AVG"], 1.000)
        self.assertEqual(pitch_type_stats[0]["SLG"], 2.000)
        self.assertEqual(pitch_type_stats[0]["ISO"], 1.000)
        batch_pitch_type_stats = database.get_batter_pitch_type_stats_batch_from_db(
            [10, 10],
            2026,
            "L",
        )
        self.assertEqual(len(batch_pitch_type_stats), 1)
        self.assertEqual(batch_pitch_type_stats[0]["batter_id"], 10)

        pitcher_pitch_mix = database.get_pitcher_pitch_type_stats_from_db(
            20,
            2026,
        )
        self.assertEqual(len(pitcher_pitch_mix), 1)
        self.assertEqual(pitcher_pitch_mix[0]["PITCH"], "Four-Seam Fastball")
        self.assertEqual(pitcher_pitch_mix[0]["COUNT"], 10)
        self.assertEqual(pitcher_pitch_mix[0]["PERCENTAGE"], 100.0)
        self.assertEqual(pitcher_pitch_mix[0]["AVG SPEED"], 96.5)
        batch_pitcher_pitch_mix = database.get_pitcher_pitch_type_stats_batch_from_db(
            [20, 20],
            2026,
        )
        self.assertEqual(len(batch_pitcher_pitch_mix), 1)
        self.assertEqual(batch_pitcher_pitch_mix[0]["pitcher_id"], 20)

        pitcher_season_logs = database.get_pitcher_season_game_logs_from_db(
            20,
            2026,
        )
        self.assertEqual(len(pitcher_season_logs), 1)
        self.assertEqual(pitcher_season_logs[0]["opponent"], "New York Yankees")
        self.assertEqual(pitcher_season_logs[0]["Pitch Count"], 88)

        pitcher_logs = database.get_pitcher_vs_team_game_logs_from_db(
            20,
            "New York Yankees",
        )
        self.assertEqual(pitcher_logs[0]["team"], "Boston Red Sox")
        self.assertEqual(pitcher_logs[0]["home_away"], "Home")
        self.assertEqual(pitcher_logs[0]["Pitch Count"], 88)

        with database.read_connection() as conn:
            table_names = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }
        self.assertNotIn("plate_appearances", table_names)

if __name__ == "__main__":
    unittest.main()
