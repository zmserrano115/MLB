import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import requests

from src.mlb_schedule import (
    get_daily_schedule,
    schedule_display_state,
    sort_schedule_for_display,
    write_cached_schedule,
)


class ScheduleTests(unittest.TestCase):
    def test_schedule_display_state_recognizes_live_and_finished_games(self):
        self.assertEqual(
            schedule_display_state(
                {
                    "abstract_game_state": "Live",
                    "game_status": "Manager Challenge",
                }
            ),
            "live",
        )
        self.assertEqual(
            schedule_display_state(
                {
                    "abstract_game_state": "",
                    "game_status": "Game Over",
                }
            ),
            "final",
        )
        self.assertEqual(
            schedule_display_state(
                {
                    "abstract_game_state": "Preview",
                    "game_status": "Scheduled",
                }
            ),
            "upcoming",
        )
        self.assertEqual(
            schedule_display_state(
                {
                    "abstract_game_state": pd.NA,
                    "game_status": pd.NA,
                }
            ),
            "upcoming",
        )

    def test_schedule_display_order_is_live_upcoming_then_final(self):
        schedule = pd.DataFrame(
            [
                {
                    "game_pk": 4,
                    "game_status": "Final",
                    "abstract_game_state": "Final",
                    "game_time_utc": "2026-07-26T17:00:00Z",
                },
                {
                    "game_pk": 3,
                    "game_status": "Scheduled",
                    "abstract_game_state": "Preview",
                    "game_time_utc": "2026-07-26T23:00:00Z",
                },
                {
                    "game_pk": 1,
                    "game_status": "In Progress",
                    "abstract_game_state": "Live",
                    "game_time_utc": "2026-07-26T19:00:00Z",
                },
                {
                    "game_pk": 2,
                    "game_status": "Scheduled",
                    "abstract_game_state": "Preview",
                    "game_time_utc": "2026-07-26T21:00:00Z",
                },
            ]
        )

        ordered = sort_schedule_for_display(schedule)

        self.assertEqual(ordered["game_pk"].tolist(), [1, 2, 3, 4])
        self.assertEqual(
            ordered["_schedule_display_state"].tolist(),
            ["live", "upcoming", "upcoming", "final"],
        )

    @patch("src.mlb_schedule.get_json")
    def test_probable_pitcher_hands_use_one_bulk_people_request(self, mock_get_json):
        schedule_payload = {
            "dates": [
                {
                    "games": [
                        {
                            "gamePk": 1,
                            "gameDate": "2026-06-01T23:10:00Z",
                            "status": {
                                "detailedState": "In Progress",
                                "abstractGameState": "Live",
                            },
                            "linescore": {
                                "currentInning": 6,
                                "currentInningOrdinal": "6th",
                                "inningState": "Top",
                                "inningHalf": "Top",
                            },
                            "venue": {
                                "id": 99,
                                "name": "Test Park",
                                "location": {
                                    "city": "Denver",
                                    "defaultCoordinates": {
                                        "latitude": 39.756,
                                        "longitude": -104.994,
                                    },
                                    "azimuthAngle": 20.0,
                                    "elevation": 5200,
                                },
                                "fieldInfo": {
                                    "roofType": "Open",
                                    "leftLine": 315,
                                    "left": 370,
                                    "leftCenter": 390,
                                    "center": 404,
                                    "rightCenter": 375,
                                    "right": 370,
                                    "rightLine": 322,
                                },
                            },
                            "teams": {
                                "away": {
                                    "team": {
                                        "id": 10,
                                        "name": "Away",
                                        "abbreviation": "AWY",
                                    },
                                    "score": 4,
                                    "probablePitcher": {
                                        "id": 100,
                                        "fullName": "Away Pitcher",
                                    },
                                },
                                "home": {
                                    "team": {
                                        "id": 20,
                                        "name": "Home",
                                        "abbreviation": "HOM",
                                    },
                                    "score": 2,
                                    "probablePitcher": {
                                        "id": 200,
                                        "fullName": "Home Pitcher",
                                    },
                                },
                            },
                        }
                    ]
                }
            ]
        }
        people_payload = {
            "people": [
                {"id": 100, "pitchHand": {"code": "R"}},
                {"id": 200, "pitchHand": {"code": "L"}},
            ]
        }
        mock_get_json.side_effect = [schedule_payload, people_payload]

        with tempfile.TemporaryDirectory() as cache_dir, patch(
            "src.mlb_schedule.SCHEDULE_CACHE_DIR",
            Path(cache_dir),
        ):
            schedule = get_daily_schedule("2026-06-01")

        self.assertEqual(mock_get_json.call_count, 2)
        self.assertEqual(schedule.iloc[0]["away_pitcher_hand"], "R")
        self.assertEqual(schedule.iloc[0]["home_pitcher_hand"], "L")
        self.assertEqual(schedule.iloc[0]["venue_name"], "Test Park")
        self.assertEqual(schedule.iloc[0]["venue_latitude"], 39.756)
        self.assertEqual(schedule.iloc[0]["field_azimuth"], 20.0)
        self.assertEqual(schedule.iloc[0]["roof_type"], "Open")
        self.assertEqual(schedule.iloc[0]["field_center"], 404)
        self.assertEqual(schedule.iloc[0]["field_dimensions"]["left_line"], 315)
        self.assertEqual(schedule.iloc[0]["away_team_abbr"], "AWY")
        self.assertEqual(schedule.iloc[0]["home_team_abbr"], "HOM")
        self.assertEqual(schedule.iloc[0]["away_score"], 4)
        self.assertEqual(schedule.iloc[0]["home_score"], 2)
        self.assertEqual(
            schedule.iloc[0]["game_time_utc"],
            "2026-06-01T23:10:00Z",
        )
        self.assertEqual(schedule.iloc[0]["abstract_game_state"], "Live")
        self.assertEqual(schedule.iloc[0]["current_inning_ordinal"], "6th")

    @patch("src.mlb_schedule.get_json")
    def test_schedule_uses_saved_copy_when_live_request_fails(self, mock_get_json):
        mock_get_json.side_effect = requests.ConnectionError("temporary DNS failure")
        saved = pd.DataFrame(
            [
                {
                    "game_date": "2026-06-24",
                    "game_pk": 123,
                    "away_team": "Away",
                    "home_team": "Home",
                }
            ]
        )

        with tempfile.TemporaryDirectory() as cache_dir, patch(
            "src.mlb_schedule.SCHEDULE_CACHE_DIR",
            Path(cache_dir),
        ):
            write_cached_schedule("2026-06-24", saved)
            schedule = get_daily_schedule("2026-06-24")

        self.assertEqual(schedule.iloc[0]["game_pk"], 123)
        self.assertEqual(schedule.attrs["schedule_source"], "saved")


if __name__ == "__main__":
    unittest.main()
