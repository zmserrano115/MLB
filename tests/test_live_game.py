import unittest

import pandas as pd

from src.live_game import (
    calculate_live_streak,
    parse_game_boxscore,
    parse_player_game_log,
)


class LiveGameBoxscoreTests(unittest.TestCase):
    def test_parse_game_boxscore_builds_hitter_and_pitcher_rows(self):
        data = {
            "teams": {
                "away": {
                    "team": {"name": "Away Team", "abbreviation": "AWY"},
                    "batters": [10],
                    "pitchers": [20],
                    "players": {
                        "ID10": {
                            "person": {"id": 10, "fullName": "Test Hitter"},
                            "position": {"abbreviation": "RF"},
                            "stats": {
                                "batting": {
                                    "atBats": 4,
                                    "runs": 1,
                                    "hits": 2,
                                    "rbi": 3,
                                    "baseOnBalls": 1,
                                    "strikeOuts": 1,
                                    "homeRuns": 1,
                                    "stolenBases": 1,
                                    "avg": ".300",
                                    "ops": ".900",
                                }
                            },
                            "seasonStats": {
                                "batting": {
                                    "avg": ".312",
                                    "ops": ".944",
                                }
                            },
                        },
                        "ID20": {
                            "person": {"id": 20, "fullName": "Test Pitcher"},
                            "position": {"abbreviation": "P"},
                            "stats": {
                                "pitching": {
                                    "inningsPitched": "6.0",
                                    "hits": 4,
                                    "runs": 2,
                                    "earnedRuns": 2,
                                    "baseOnBalls": 1,
                                    "strikeOuts": 8,
                                    "homeRuns": 1,
                                    "pitchesThrown": 91,
                                    "strikes": 61,
                                    "era": "3.00",
                                    "whip": "1.10",
                                }
                            },
                            "seasonStats": {
                                "pitching": {
                                    "era": "2.75",
                                    "whip": "1.05",
                                }
                            },
                        },
                    },
                },
                "home": {
                    "team": {"name": "Home Team", "abbreviation": "HOM"},
                    "players": {},
                },
            }
        }

        boxscore = parse_game_boxscore(data)

        hitter = boxscore["batting"].iloc[0]
        self.assertEqual(hitter["Player"], "Test Hitter")
        self.assertEqual(hitter["Team"], "AWY")
        self.assertEqual(hitter["PA"], 5)
        self.assertEqual(hitter["HR"], 1)
        self.assertEqual(hitter["AVG"], ".312")
        self.assertEqual(hitter["OPS"], ".944")
        self.assertIn("/people/10/headshot/", hitter["Headshot"])

        pitcher = boxscore["pitching"].iloc[0]
        self.assertEqual(pitcher["Player"], "Test Pitcher")
        self.assertEqual(pitcher["SO"], 8)
        self.assertEqual(pitcher["PC-ST"], "91-61")
        self.assertEqual(pitcher["ERA"], "2.75")
        self.assertEqual(pitcher["WHIP"], "1.05")


class LiveStreakTests(unittest.TestCase):
    def test_live_stat_extends_historical_streak(self):
        logs = pd.DataFrame(
            [
                {"game_date": "2026-06-15", "H": 1},
                {"game_date": "2026-06-14", "H": 2},
                {"game_date": "2026-06-13", "H": 0},
            ]
        )

        result = calculate_live_streak(
            logs,
            "H",
            1,
            current_value=1,
            current_game_state="Live",
            selected_date="2026-06-16",
            live_played=True,
        )

        self.assertEqual(result["streak"], 3)
        self.assertEqual(result["status"], "Live +1")

    def test_final_game_without_threshold_ends_streak(self):
        logs = pd.DataFrame(
            [
                {"game_date": "2026-06-15", "SO": 7},
                {"game_date": "2026-06-14", "SO": 8},
            ]
        )

        result = calculate_live_streak(
            logs,
            "SO",
            7,
            current_value=5,
            current_game_state="Final",
            selected_date="2026-06-16",
            live_played=True,
        )

        self.assertEqual(result["streak"], 0)
        self.assertEqual(result["status"], "Ended")


class PlayerGameLogTests(unittest.TestCase):
    def test_parse_hitter_game_log_includes_complete_display_stats(self):
        data = {
            "stats": [
                {
                    "splits": [
                        {
                            "date": "2026-06-17",
                            "isHome": True,
                            "game": {"gamePk": 123},
                            "team": {"abbreviation": "ATH"},
                            "opponent": {"name": "Houston Astros"},
                            "stat": {
                                "plateAppearances": 5,
                                "atBats": 4,
                                "hits": 2,
                                "totalBases": 5,
                                "baseOnBalls": 1,
                                "hitByPitch": 0,
                                "sacFlies": 0,
                                "homeRuns": 1,
                                "rbi": 2,
                                "runs": 1,
                                "stolenBases": 0,
                                "strikeOuts": 1,
                            },
                        }
                    ]
                }
            ]
        }

        row = parse_player_game_log(data, "hitting").iloc[0]

        self.assertEqual(row["game_pk"], 123)
        self.assertEqual(row["home_away"], "Home")
        self.assertEqual(row["TB"], 5)
        self.assertEqual(row["OPS"], 1.85)
        self.assertEqual(row["K%"], 20.0)
        self.assertEqual(row["BB%"], 20.0)


if __name__ == "__main__":
    unittest.main()
