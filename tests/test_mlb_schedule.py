import unittest
from unittest.mock import Mock, patch

from src.mlb_schedule import get_daily_schedule


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
                            "teams": {
                                "away": {
                                    "team": {"id": 10, "name": "Away"},
                                    "probablePitcher": {
                                        "id": 100,
                                        "fullName": "Away Pitcher",
                                    },
                                },
                                "home": {
                                    "team": {"id": 20, "name": "Home"},
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

        schedule = get_daily_schedule("2026-06-01")

        self.assertEqual(mock_get.call_count, 2)
        self.assertEqual(schedule.iloc[0]["away_pitcher_hand"], "R")
        self.assertEqual(schedule.iloc[0]["home_pitcher_hand"], "L")


if __name__ == "__main__":
    unittest.main()
