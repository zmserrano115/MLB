import tempfile
from pathlib import Path
import unittest

from src import database


class DatabaseTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        database.DB_PATH = Path(self.temp_dir.name) / "test.db"
        database._INITIALIZED_PATH = None
        database.init_database()

    def tearDown(self):
        self.temp_dir.cleanup()

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

        game_logs = database.get_batter_vs_pitcher_game_logs_from_db(10, 20)
        self.assertEqual(len(game_logs), 1)
        self.assertEqual(game_logs[0]["home_away"], "Away")
        self.assertEqual(game_logs[0]["TB"], 2)

        pitcher_stats = database.get_pitcher_stats_from_db(2026, 20)
        self.assertEqual(pitcher_stats["starts"], 1)
        self.assertEqual(pitcher_stats["IP"], 5.1)
        self.assertEqual(pitcher_stats["projected_pitch_count"], 88)

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
