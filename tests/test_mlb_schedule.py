import unittest
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch

import pandas as pd
import requests

from src.mlb_schedule import get_daily_schedule, write_cached_schedule


class ScheduleTests(unittest.TestCase):
    @patch("src.mlb_schedule.requests.get")
    def test_probable_pitcher_hands_use_one_bulk_people_request(self, mock_get):
        schedule_response = Mock()
        schedule_response.raise_for_status.return_value = None
        schedule_response.json.return_value = {
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
                                "fieldInfo": {"roofType": "Open"},
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
        people_response = Mock()
        people_response.raise_for_status.return_value = None
        people_response.json.return_value = {
            "people": [
                {"id": 100, "pitchHand": {"code": "R"}},
                {"id": 200, "pitchHand": {"code": "L"}},
            ]
        }
        mock_get.side_effect = [schedule_response, people_response]

        with tempfile.TemporaryDirectory() as cache_dir, patch(
            "src.mlb_schedule.SCHEDULE_CACHE_DIR",
            Path(cache_dir),
        ):
            schedule = get_daily_schedule("2026-06-01")

        self.assertEqual(mock_get.call_count, 2)
        self.assertEqual(schedule.iloc[0]["away_pitcher_hand"], "R")
        self.assertEqual(schedule.iloc[0]["home_pitcher_hand"], "L")
        self.assertEqual(schedule.iloc[0]["venue_name"], "Test Park")
        self.assertEqual(schedule.iloc[0]["venue_latitude"], 39.756)
        self.assertEqual(schedule.iloc[0]["field_azimuth"], 20.0)
        self.assertEqual(schedule.iloc[0]["roof_type"], "Open")
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

    @patch("src.mlb_schedule.requests.get")
    def test_schedule_uses_saved_copy_when_live_request_fails(self, mock_get):
        mock_get.side_effect = requests.ConnectionError("temporary DNS failure")
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
