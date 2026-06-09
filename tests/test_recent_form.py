import unittest

import pandas as pd

from src.recent_form import build_recent_bar_chart_html, recent_game_values


class RecentFormTests(unittest.TestCase):
    def setUp(self):
        self.logs = pd.DataFrame(
            [
                {"game_date": "2026-06-06", "TB": 2, "SO": 8, "home_away": "Home"},
                {"game_date": "2026-06-05", "TB": 0, "SO": 5, "home_away": "Away"},
                {"game_date": "2026-06-04", "TB": 4, "SO": 10, "home_away": "Home"},
                {"game_date": "2026-06-03", "TB": 1, "SO": 7, "home_away": "Away"},
                {"game_date": "2026-06-02", "TB": 3, "SO": 9, "home_away": "Home"},
                {"game_date": "2026-06-01", "TB": 1, "SO": 4, "home_away": "Away"},
            ]
        )

    def test_recent_values_use_latest_five_in_chronological_chart_order(self):
        values = recent_game_values(self.logs, "TB")
        self.assertEqual([item["date"] for item in values], [
            "6/2 (H)",
            "6/3 (A)",
            "6/4 (H)",
            "6/5 (A)",
            "6/6 (H)",
        ])
        self.assertEqual([item["value"] for item in values], [3, 1, 4, 0, 2])

    def test_chart_is_compact_and_contains_all_five_values(self):
        chart = build_recent_bar_chart_html(
            self.logs,
            value_column="SO",
            title="Strikeouts - Last 5 Appearances",
            subtitle="Test Pitcher vs Test Team",
            scale_floor=10,
        )
        self.assertIn("recent-bar-grid", chart)
        self.assertIn("Test Pitcher vs Test Team", chart)
        self.assertEqual(chart.count('class="recent-bar-item"'), 5)


if __name__ == "__main__":
    unittest.main()
