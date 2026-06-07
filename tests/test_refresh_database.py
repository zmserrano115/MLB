import unittest

from refresh_database import (
    ip_to_outs,
    outs_to_baseball_ip,
    parse_game_to_batter_pitcher_logs,
    parse_pitcher_game_logs,
)


class StatsApiParserTests(unittest.TestCase):
    def test_completed_game_feed_is_aggregated_without_raw_pa_storage(self):
        game = {
            "game_pk": 99,
            "game_date": "2026-06-01",
            "season": 2026,
            "away_team": "New York Yankees",
            "home_team": "Boston Red Sox",
        }
        feed = {
            "liveData": {
                "plays": {
                    "allPlays": [
                        {
                            "matchup": {
                                "batter": {"id": 10, "fullName": "Batter"},
                                "pitcher": {"id": 20, "fullName": "Pitcher"},
                            },
                            "result": {"eventType": "double", "rbi": 1},
                            "about": {"halfInning": "top"},
                        },
                        {
                            "matchup": {
                                "batter": {"id": 10, "fullName": "Batter"},
                                "pitcher": {"id": 20, "fullName": "Pitcher"},
                            },
                            "result": {"eventType": "walk", "rbi": 0},
                            "about": {"halfInning": "top"},
                        },
                    ]
                },
                "boxscore": {
                    "teams": {
                        "home": {
                            "pitchers": [20],
                            "players": {
                                "ID20": {
                                    "person": {"fullName": "Pitcher"},
                                    "stats": {
                                        "pitching": {
                                            "inningsPitched": "5.1",
                                            "numberOfPitches": 88,
                                            "battersFaced": 22,
                                            "hits": 5,
                                            "baseOnBalls": 2,
                                            "hitBatsmen": 0,
                                            "strikeOuts": 7,
                                            "homeRuns": 1,
                                            "runs": 2,
                                            "earnedRuns": 2,
                                        }
                                    },
                                }
                            },
                        },
                        "away": {"pitchers": [], "players": {}},
                    }
                },
            }
        }

        players, logs, pa_count = parse_game_to_batter_pitcher_logs(feed, game)
        self.assertEqual(pa_count, 2)
        self.assertEqual(players[10], "Batter")
        self.assertEqual(len(logs), 1)
        self.assertEqual(logs[0]["PA"], 2)
        self.assertEqual(logs[0]["AB"], 1)
        self.assertEqual(logs[0]["doubles"], 1)
        self.assertEqual(logs[0]["TB"], 2)

        _, pitcher_logs = parse_pitcher_game_logs(feed, game)
        self.assertEqual(pitcher_logs[0]["IP_outs"], 16)
        self.assertEqual(pitcher_logs[0]["IP"], 5.1)

    def test_baseball_innings_conversion(self):
        self.assertEqual(ip_to_outs("6.2"), 20)
        self.assertEqual(outs_to_baseball_ip(20), 6.2)


if __name__ == "__main__":
    unittest.main()
