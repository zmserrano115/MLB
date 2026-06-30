import gzip
import io
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

from src import database


class DatabaseTests(unittest.TestCase):
    def setUp(self):
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

    def test_download_database_expands_gzip_release_asset(self):
        payload = b"SQLite format 3\x00" + (b"database-bytes" * 10)
        compressed = gzip.compress(payload)
        target = Path(self.temp_dir.name) / "downloaded.db"

        with patch(
            "src.database.urllib.request.urlopen",
            return_value=io.BytesIO(compressed),
        ):
            database._download_database(
                "https://example.test/mlb.db.gz",
                target,
            )

        self.assertEqual(target.read_bytes(), payload)

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

        database.save_completed_game(
            game=game,
            players={10: "Test Batter", 20: "Test Pitcher"},
            batter_pitcher_logs=[bvp_log],
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
