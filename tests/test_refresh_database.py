import unittest

from refresh_database import (
    ip_to_outs,
    outs_to_baseball_ip,
    parse_game_to_batter_pitch_type_logs,
    parse_game_to_batter_pitcher_logs,
    parse_game_to_pitcher_pitch_type_logs,
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
                                "pitchHand": {"code": "L"},
                            },
                            "result": {"eventType": "double", "rbi": 1},
                            "about": {"halfInning": "top"},
                            "playEvents": [
                                {
                                    "isPitch": True,
                                    "details": {
                                        "type": {
                                            "code": "FF",
                                            "description": "Four-Seam Fastball",
                                        }
                                    },
                                    "pitchData": {"startSpeed": 96.8},
                                }
                            ],
                        },
                        {
                            "matchup": {
                                "batter": {"id": 10, "fullName": "Batter"},
                                "pitcher": {"id": 20, "fullName": "Pitcher"},
                                "pitchHand": {"code": "L"},
                            },
                            "result": {"eventType": "walk", "rbi": 0},
                            "about": {"halfInning": "top"},
                            "playEvents": [
                                {
                                    "isPitch": True,
                                    "details": {
                                        "type": {
                                            "code": "SL",
                                            "description": "Slider",
                                        }
                                    },
                                    "pitchData": {"startSpeed": 84.2},
                                }
                            ],
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

        pitch_types, pitch_type_logs = parse_game_to_batter_pitch_type_logs(
            feed,
            game,
        )
        self.assertEqual(pitch_types["FF"], "Four-Seam Fastball")
        self.assertEqual(pitch_types["SL"], "Slider")
        pitch_logs_by_code = {
            row["pitch_code"]: row
            for row in pitch_type_logs
        }
        self.assertEqual(pitch_logs_by_code["FF"]["pitcher_hand"], "L")
        self.assertEqual(pitch_logs_by_code["FF"]["AB"], 1)
        self.assertEqual(pitch_logs_by_code["FF"]["H"], 1)
        self.assertEqual(pitch_logs_by_code["FF"]["doubles"], 1)
        self.assertEqual(pitch_logs_by_code["FF"]["TB"], 2)
        self.assertEqual(pitch_logs_by_code["SL"]["PA"], 1)
        self.assertEqual(pitch_logs_by_code["SL"]["AB"], 0)
        self.assertEqual(pitch_logs_by_code["SL"]["BB"], 1)

        pitch_mix_players, pitcher_pitch_types, pitcher_pitch_logs = (
            parse_game_to_pitcher_pitch_type_logs(feed, game)
        )
        self.assertEqual(pitch_mix_players[20], "Pitcher")
        self.assertEqual(pitcher_pitch_types["FF"], "Four-Seam Fastball")
        pitch_mix_by_code = {
            row["pitch_code"]: row
            for row in pitcher_pitch_logs
        }
        self.assertEqual(pitch_mix_by_code["FF"]["pitch_count"], 1)
        self.assertEqual(pitch_mix_by_code["FF"]["measured_pitches"], 1)
        self.assertEqual(pitch_mix_by_code["FF"]["total_speed"], 96.8)
        self.assertEqual(pitch_mix_by_code["SL"]["pitch_count"], 1)

        _, pitcher_logs = parse_pitcher_game_logs(feed, game)
        self.assertEqual(pitcher_logs[0]["IP_outs"], 16)
        self.assertEqual(pitcher_logs[0]["IP"], 5.1)

    def test_baseball_innings_conversion(self):
        self.assertEqual(ip_to_outs("6.2"), 20)
        self.assertEqual(outs_to_baseball_ip(20), 6.2)


if __name__ == "__main__":
    unittest.main()
