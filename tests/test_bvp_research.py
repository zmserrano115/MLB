import unittest

import pandas as pd

from src.bvp_research import (
    game_context,
    game_options,
    opponent_context_for_batter,
    player_search_options,
    team_record_from_game_context,
)


class BvpResearchTests(unittest.TestCase):
    def test_game_and_player_options_preserve_ids(self):
        schedule = pd.DataFrame(
            [
                {
                    "game_pk": 123,
                    "game": "Yankees @ Red Sox",
                    "game_status": "Preview",
                }
            ]
        )
        players = pd.DataFrame(
            [{"player_id": 99, "Name": "Test Batter", "Team": "NYY"}]
        )
        self.assertEqual(list(game_options(schedule).values()), [123])
        self.assertEqual(list(player_search_options(players).values()), [99])

    def test_opponent_context_selects_probable_starter(self):
        schedule = pd.DataFrame(
            [
                {
                    "game_pk": 123,
                    "game": "Yankees @ Red Sox",
                    "away_team": "New York Yankees",
                    "away_team_id": 147,
                    "away_team_abbr": "NYY",
                    "away_probable_pitcher": "Away Starter",
                    "away_probable_pitcher_id": 1,
                    "home_team": "Boston Red Sox",
                    "home_team_id": 111,
                    "home_team_abbr": "BOS",
                    "home_probable_pitcher": "Home Starter",
                    "home_probable_pitcher_id": 2,
                }
            ]
        )
        row = game_context(schedule, 123)
        context = opponent_context_for_batter(row, {"player_id": 99, "team_id": 147})
        self.assertEqual(context["opponent_team_id"], 111)
        self.assertEqual(context["probable_pitcher_id"], 2)
        self.assertEqual(context["batter_team_side"], "away")
        self.assertEqual(team_record_from_game_context(row, 111), (111, "Boston Red Sox", "BOS"))

    def test_missing_probable_starter_is_safe(self):
        row = {
            "away_team_id": 147,
            "home_team_id": 111,
            "home_team": "Boston Red Sox",
        }
        context = opponent_context_for_batter(row, {"team_id": 147})
        self.assertIsNone(context["probable_pitcher_id"])
        self.assertEqual(context["opponent_team_id"], 111)


if __name__ == "__main__":
    unittest.main()
