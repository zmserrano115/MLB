import unittest

from src.matchups import weather_adjusted_hitter_grade


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


if __name__ == "__main__":
    unittest.main()
