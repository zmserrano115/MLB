import unittest

import pandas as pd

from src.matchup_grading import grade_hitter_matchup
from src.matchups import weather_adjusted_hitter_grade
from src.scoring import score_pitcher_k_matchup


class MatchupWeatherTests(unittest.TestCase):
    def test_material_weather_edge_moves_hitter_grade_one_level(self):
        self.assertEqual(
            weather_adjusted_hitter_grade("Neutral", 3.0),
            "Good Matchup",
        )
        self.assertEqual(
            weather_adjusted_hitter_grade("Good Matchup", -3.0),
            "Neutral",
        )

    def test_weather_does_not_override_missing_history_labels(self):
        self.assertEqual(
            weather_adjusted_hitter_grade("No History", 6.0),
            "No History",
        )
        self.assertEqual(
            weather_adjusted_hitter_grade("Small Sample", -6.0),
            "Small Sample",
        )

    def test_weather_cannot_promote_a_good_matchup_to_strong(self):
        self.assertEqual(
            weather_adjusted_hitter_grade("Good Matchup", 6.0),
            "Good Matchup",
        )

    def test_weather_cannot_promote_an_avoid_grade(self):
        self.assertEqual(
            weather_adjusted_hitter_grade("Avoid", 6.0),
            "Avoid",
        )


class HitterMatchupGradingTests(unittest.TestCase):
    def test_strong_matchup_uses_only_requested_ab_and_average_rules(self):
        self.assertEqual(grade_hitter_matchup(8, 0.401), "Strong Matchup")
        self.assertEqual(grade_hitter_matchup(26, 0.300), "Strong Matchup")
        self.assertNotEqual(grade_hitter_matchup(8, 0.400), "Strong Matchup")
        self.assertNotEqual(grade_hitter_matchup(25, 0.300), "Strong Matchup")

    def test_below_200_is_always_avoid(self):
        self.assertEqual(grade_hitter_matchup(4, 0.199), "Avoid")
        self.assertEqual(grade_hitter_matchup(50, 0.199), "Avoid")

    def test_remaining_grades_are_sample_and_hit_focused(self):
        self.assertEqual(grade_hitter_matchup(0, 0), "No History")
        self.assertEqual(grade_hitter_matchup(7, 0.300), "Small Sample")
        self.assertEqual(grade_hitter_matchup(12, 0.325), "Good Matchup")
        self.assertEqual(grade_hitter_matchup(30, 0.275), "Good Matchup")
        self.assertEqual(grade_hitter_matchup(12, 0.240), "Neutral")


class PitcherProjectionTests(unittest.TestCase):
    def test_projected_hits_uses_pitcher_rate_and_opponent_average(self):
        pitcher = pd.Series(
            {
                "player_id": 20,
                "Name": "Test Pitcher",
                "Team": "BOS",
                "IP": 60.0,
                "GS": 10,
                "Pitches": 900,
                "H": 50,
                "K%": 25.0,
                "K/9": 9.0,
            }
        )
        opposing_batters = pd.DataFrame(
            {
                "K%": [22.0, 22.0],
                "AVG": [0.294, 0.294],
            }
        )

        result = score_pitcher_k_matchup(pitcher, opposing_batters)

        self.assertAlmostEqual(result["Projected IP"], 6.0)
        self.assertAlmostEqual(result["Projected Hits"], 6.0)


if __name__ == "__main__":
    unittest.main()
