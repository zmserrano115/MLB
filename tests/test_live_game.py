import unittest

import pandas as pd

from src.live_game import (
    calculate_team_record_vs_pitcher,
    calculate_team_win_streak,
    calculate_live_streak,
    classify_play_result,
    parse_game_boxscore,
    parse_live_game_feed,
    parse_player_game_log,
    parse_player_profile,
    parse_team_schedule_results,
    parse_team_roster,
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
                            "battingOrder": "300",
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
        self.assertEqual(hitter["Lineup"], 3)
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


class LiveGameFeedTests(unittest.TestCase):
    def test_parse_live_feed_includes_count_bases_and_next_hitters(self):
        data = {
            "gameData": {
                "game": {"pk": 99},
                "status": {
                    "abstractGameState": "Live",
                    "detailedState": "In Progress",
                },
                "teams": {
                    "away": {"id": 10, "name": "Away Team"},
                    "home": {"id": 20, "name": "Home Team"},
                },
                "venue": {
                    "name": "Test Ballpark",
                    "fieldInfo": {
                        "leftLine": 315,
                        "left": 370,
                        "leftCenter": 410,
                        "center": 404,
                        "rightCenter": 404,
                        "right": 370,
                        "rightLine": 322,
                    },
                },
                "absChallenges": {
                    "hasChallenges": True,
                    "away": {
                        "remaining": 1,
                        "usedSuccessful": 0,
                        "usedFailed": 1,
                    },
                    "home": {
                        "remaining": 1,
                        "usedSuccessful": 1,
                        "usedFailed": 1,
                    },
                },
            },
            "liveData": {
                "boxscore": {
                    "teams": {
                        "away": {
                            "players": {
                                "ID9": {
                                    "stats": {
                                        "pitching": {
                                            "pitchesThrown": 88,
                                            "strikeOuts": 9,
                                            "hits": 5,
                                            "era": "2.91",
                                        }
                                    }
                                }
                            }
                        },
                        "home": {
                            "players": {
                                "ID1": {
                                    "person": {"id": 1, "fullName": "Current Batter"},
                                    "battingOrder": "200",
                                },
                                "ID2": {
                                    "person": {"id": 2, "fullName": "On Deck Hitter"},
                                    "battingOrder": "300",
                                },
                            }
                        },
                    }
                },
                "linescore": {
                    "currentInning": 7,
                    "currentInningOrdinal": "7th",
                    "inningState": "Top",
                    "teams": {
                        "away": {"runs": 4},
                        "home": {"runs": 2},
                    },
                    "offense": {
                        "batter": {"id": 1, "fullName": "Current Batter"},
                        "onDeck": {"id": 2, "fullName": "On Deck Hitter"},
                        "first": {"id": 3, "fullName": "Runner One"},
                    },
                },
                "plays": {
                    "currentPlay": {
                        "count": {"balls": 2, "strikes": 1, "outs": 1},
                        "matchup": {
                            "batter": {"id": 1, "fullName": "Current Batter"},
                            "pitcher": {"id": 9, "fullName": "Current Pitcher"},
                            "pitchHand": {"code": "L"},
                        },
                        "playEvents": [
                            {
                                "isPitch": True,
                                "details": {"description": "Foul"},
                                "count": {"balls": 2, "strikes": 1, "outs": 1},
                            },
                            {
                                "isPitch": True,
                                "details": {"description": "Foul Ball"},
                                "count": {"balls": 2, "strikes": 1, "outs": 1},
                            },
                        ],
                    },
                    "allPlays": [
                    {
                        "about": {
                            "atBatIndex": 4,
                            "inning": 7,
                            "halfInning": "top",
                            "isComplete": True,
                            "isScoringPlay": True,
                        },
                        "matchup": {
                            "batter": {"id": 1, "fullName": "Current Batter"},
                            "pitcher": {"id": 9, "fullName": "Current Pitcher"},
                        },
                        "result": {
                            "event": "Home Run",
                            "eventType": "home_run",
                            "description": "Current Batter homers to left field.",
                            "awayScore": 4,
                            "homeScore": 2,
                        },
                        "count": {"balls": 1, "strikes": 2, "outs": 1},
                        "playEvents": [
                            {
                                "isPitch": True,
                                "count": {"balls": 1, "strikes": 1, "outs": 1},
                            },
                            {
                                "isPitch": True,
                                "count": {"balls": 1, "strikes": 2, "outs": 1},
                                "hitData": {
                                    "launchSpeed": 103.4,
                                    "launchAngle": 27,
                                    "totalDistance": 421,
                                    "trajectory": "fly_ball",
                                    "location": "7",
                                    "coordinates": {
                                        "coordX": 72.5,
                                        "coordY": 48.25,
                                    },
                                },
                            },
                        ],
                        "runners": [
                            {"details": {"isScoringEvent": True}},
                            {"details": {"isScoringEvent": True}},
                        ],
                    }
                    ],
                },
            },
        }

        parsed = parse_live_game_feed(data)

        self.assertEqual(parsed["inning_ordinal"], "7th")
        self.assertEqual(parsed["balls"], 2)
        self.assertEqual(parsed["current_batter"]["name"], "Current Batter")
        self.assertEqual(parsed["current_batter"]["lineup_number"], 2)
        self.assertEqual(parsed["current_pitcher"]["name"], "Current Pitcher")
        self.assertEqual(parsed["current_pitcher"]["pitch_count"], 88)
        self.assertEqual(parsed["current_pitcher"]["strikeouts"], 9)
        self.assertEqual(parsed["current_pitcher"]["hits_allowed"], 5)
        self.assertEqual(parsed["current_pitcher"]["era"], "2.91")
        self.assertEqual(parsed["current_pitcher"]["throwing_hand"], "L")
        self.assertEqual(parsed["on_deck"]["name"], "On Deck Hitter")
        self.assertEqual(parsed["on_deck"]["lineup_number"], 3)
        self.assertEqual(parsed["fouls"], 2)
        self.assertEqual(parsed["current_pitches"][0]["count_before"]["strikes"], 0)
        self.assertEqual(parsed["current_pitches"][1]["count_before"]["strikes"], 1)
        self.assertEqual(parsed["bases"]["first"]["name"], "Runner One")
        self.assertIn(
            "/people/3/headshot/",
            parsed["bases"]["first"]["headshot"],
        )
        self.assertIsNone(parsed["bases"]["second"])
        self.assertEqual(parsed["recent_plays"][0]["result_type"], "home_run")
        self.assertEqual(parsed["recent_plays"][0]["runs_scored"], 2)
        self.assertEqual(parsed["venue_name"], "Test Ballpark")
        self.assertEqual(parsed["field_dimensions"]["left_line"], 315)
        self.assertEqual(parsed["field_dimensions"]["center"], 404)
        self.assertTrue(parsed["abs_challenges"]["enabled"])
        self.assertEqual(parsed["abs_challenges"]["away"]["remaining"], 1)
        self.assertEqual(parsed["abs_challenges"]["home"]["successful"], 1)
        self.assertEqual(parsed["latest_batted_ball"]["hit_data"]["x"], 72.5)
        self.assertEqual(
            parsed["latest_batted_ball"]["hit_data"]["distance"],
            421.0,
        )
        self.assertEqual(
            parsed["recent_plays"][0]["count_before"]["strikes"],
            1,
        )
        self.assertEqual(
            parsed["recent_plays"][0]["pitches"][1]["count_before"]["strikes"],
            1,
        )
        self.assertEqual(len(parsed["completed_plays"]), 1)

    def test_current_strike_zone_does_not_reuse_completed_at_bat_pitches(self):
        data = {
            "gameData": {
                "game": {"pk": 99},
                "status": {
                    "abstractGameState": "Live",
                    "detailedState": "In Progress",
                },
                "teams": {
                    "away": {"id": 10, "name": "Away Team"},
                    "home": {"id": 20, "name": "Home Team"},
                },
            },
            "liveData": {
                "boxscore": {"teams": {"away": {"players": {}}, "home": {"players": {}}}},
                "linescore": {
                    "currentInning": 1,
                    "currentInningOrdinal": "1st",
                    "inningState": "Top",
                    "teams": {"away": {"runs": 0}, "home": {"runs": 0}},
                    "offense": {
                        "batter": {"id": 2, "fullName": "New Batter"},
                    },
                },
                "plays": {
                    "currentPlay": {
                        "count": {"balls": 0, "strikes": 0, "outs": 1},
                        "matchup": {
                            "batter": {"id": 2, "fullName": "New Batter"},
                            "pitcher": {"id": 9, "fullName": "Current Pitcher"},
                        },
                        "playEvents": [],
                    },
                    "allPlays": [
                        {
                            "about": {
                                "atBatIndex": 1,
                                "inning": 1,
                                "halfInning": "top",
                                "isComplete": True,
                            },
                            "matchup": {
                                "batter": {"id": 1, "fullName": "Old Batter"},
                                "pitcher": {"id": 9, "fullName": "Current Pitcher"},
                            },
                            "result": {
                                "event": "Strikeout",
                                "eventType": "strikeout",
                                "description": "Old Batter strikes out.",
                            },
                            "playEvents": [
                                {
                                    "isPitch": True,
                                    "details": {
                                        "description": "Called Strike",
                                        "isStrike": True,
                                        "zone": 5,
                                    },
                                    "count": {"balls": 0, "strikes": 1, "outs": 0},
                                }
                            ],
                        }
                    ],
                },
            },
        }

        parsed = parse_live_game_feed(data)

        self.assertEqual(parsed["current_batter"]["name"], "New Batter")
        self.assertEqual(parsed["current_pitches"], [])
        self.assertIsNone(parsed["latest_pitch"])

    def test_play_result_classification_covers_common_events(self):
        self.assertEqual(
            classify_play_result({"event": "Groundout", "eventType": "field_out"}),
            "groundout",
        )
        self.assertEqual(
            classify_play_result(
                {"event": "Grounded Into DP", "eventType": "grounded_into_double_play"}
            ),
            "double_play",
        )
        self.assertEqual(
            classify_play_result({"event": "Hit By Pitch", "eventType": "hit_by_pitch"}),
            "hit_by_pitch",
        )

    def test_parse_player_profile_uses_current_team_and_position(self):
        parsed = parse_player_profile(
            {
                "people": [
                    {
                        "id": 7,
                        "fullName": "Profile Player",
                        "currentTeam": {"id": 147, "name": "New York Yankees"},
                        "primaryPosition": {
                            "abbreviation": "RF",
                            "name": "Outfielder",
                        },
                    }
                ]
            }
        )

        self.assertEqual(parsed["team"], "New York Yankees")
        self.assertEqual(parsed["position"], "RF")
        self.assertIn("/people/7/headshot/", parsed["headshot"])

    def test_parse_team_roster_assigns_profile_group(self):
        roster = parse_team_roster(
            {
                "roster": [
                    {
                        "person": {"id": 1, "fullName": "Roster Pitcher"},
                        "position": {
                            "abbreviation": "P",
                            "type": "Pitcher",
                        },
                        "status": {"description": "Active"},
                    },
                    {
                        "person": {"id": 2, "fullName": "Roster Hitter"},
                        "position": {
                            "abbreviation": "CF",
                            "type": "Outfielder",
                        },
                        "status": {"description": "Active"},
                    },
                ]
            },
            team_id=147,
            team_name="New York Yankees",
            team_abbr="NYY",
        )

        self.assertEqual(roster.iloc[0]["group"], "pitching")
        self.assertEqual(roster.iloc[1]["group"], "batting")
        self.assertEqual(roster.iloc[1]["Team"], "NYY")


class TeamStreakTests(unittest.TestCase):
    def setUp(self):
        self.schedule_data = {
            "dates": [
                {
                    "date": "2026-06-20",
                    "games": [
                        {
                            "gamePk": 1,
                            "gameDate": "2026-06-20T20:00:00Z",
                            "status": {
                                "abstractGameState": "Final",
                                "detailedState": "Final",
                            },
                            "teams": {
                                "away": {
                                    "score": 5,
                                    "team": {
                                        "id": 10,
                                        "name": "Away Team",
                                        "abbreviation": "AWY",
                                    },
                                },
                                "home": {
                                    "score": 3,
                                    "team": {
                                        "id": 20,
                                        "name": "Home Team",
                                        "abbreviation": "HOM",
                                    },
                                },
                            },
                        }
                    ],
                },
                {
                    "date": "2026-06-21",
                    "games": [
                        {
                            "gamePk": 2,
                            "gameDate": "2026-06-21T20:00:00Z",
                            "status": {
                                "abstractGameState": "Final",
                                "detailedState": "Final",
                            },
                            "teams": {
                                "away": {
                                    "score": 2,
                                    "team": {
                                        "id": 30,
                                        "name": "Third Team",
                                        "abbreviation": "THD",
                                    },
                                },
                                "home": {
                                    "score": 6,
                                    "team": {
                                        "id": 10,
                                        "name": "Away Team",
                                        "abbreviation": "AWY",
                                    },
                                },
                            },
                        }
                    ],
                },
            ]
        }

    def test_team_results_support_win_streak_and_pitcher_record(self):
        results = parse_team_schedule_results(self.schedule_data)
        pitcher_logs = pd.DataFrame(
            [
                {
                    "player_id": 50,
                    "game_pk": 1,
                    "opponent_id": 10,
                    "opponent": "Away Team",
                    "GS": 1,
                }
            ]
        )

        self.assertEqual(calculate_team_win_streak(results, 10), 2)
        self.assertEqual(
            calculate_team_record_vs_pitcher(results, pitcher_logs, 10, 50),
            {"wins": 1, "losses": 0, "games": 1},
        )


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

    def test_final_game_with_threshold_extends_streak(self):
        logs = pd.DataFrame(
            [
                {"game_date": "2026-06-17", "SO": 8},
                {"game_date": "2026-06-16", "SO": 7},
                {"game_date": "2026-06-15", "SO": 4},
            ]
        )

        result = calculate_live_streak(
            logs,
            "SO",
            7,
            current_value=7,
            current_game_state="Final",
            selected_date="2026-06-18",
            live_played=True,
        )

        self.assertEqual(result["streak"], 3)
        self.assertEqual(result["today_value"], 7)
        self.assertEqual(result["status"], "Final +1")


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
                            "opponent": {
                                "id": 117,
                                "name": "Houston Astros",
                            },
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
        self.assertEqual(row["opponent_id"], 117)
        self.assertEqual(row["home_away"], "Home")
        self.assertEqual(row["TB"], 5)
        self.assertEqual(row["OPS"], 1.85)
        self.assertEqual(row["K%"], 20.0)
        self.assertEqual(row["BB%"], 20.0)


if __name__ == "__main__":
    unittest.main()
