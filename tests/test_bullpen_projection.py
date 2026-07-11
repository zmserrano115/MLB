import unittest

import pandas as pd

from src.bullpen_projection import (
    active_status_reason,
    availability_from_workload,
    build_projected_bullpen,
    classify_pitcher_role,
    composite_bullpen_matchup,
    normalize_appearance_probabilities,
    workload_summary,
)


class BullpenProjectionTests(unittest.TestCase):
    def test_role_classification_excludes_rotation_starter(self):
        role = classify_pitcher_role(
            {"G": 12, "GS": 10, "IP": 65, "BF": 250},
            [{"is_starter": 1}, {"is_starter": 1}],
        )
        self.assertEqual(role, "Starter")

    def test_role_classification_recognizes_closer_and_lefty(self):
        self.assertEqual(classify_pitcher_role({"G": 30, "GS": 0, "SV": 10}), "Closer")
        self.assertEqual(
            classify_pitcher_role({"G": 20, "GS": 0}, throws="L"),
            "Left-Handed Specialist",
        )

    def test_status_reason_marks_inactive_pitchers(self):
        self.assertEqual(active_status_reason("10-day injured list"), "injured")
        self.assertEqual(active_status_reason("Optioned to minors"), "optioned")
        self.assertIsNone(active_status_reason("Active"))

    def test_workload_summary_counts_recent_usage(self):
        workload = workload_summary(
            [
                {"game_date": "2026-07-10", "pitch_count": 18, "IP_outs": 3},
                {"game_date": "2026-07-09", "pitch_count": 20, "IP_outs": 4},
                {"game_date": "2026-07-06", "pitch_count": 9, "IP_outs": 2},
            ],
            "2026-07-11",
        )
        self.assertEqual(workload["pitches_yesterday"], 18)
        self.assertEqual(workload["pitches_last_two_days"], 38)
        self.assertEqual(workload["consecutive_days_used"], 2)

    def test_availability_penalizes_heavy_usage_and_doubleheader(self):
        workload = {
            "pitches_yesterday": 34,
            "pitches_last_two_days": 55,
            "pitches_last_three_days": 70,
            "consecutive_days_used": 2,
            "recent_innings_pitched": 3.1,
            "appeared_earlier_today": False,
        }
        result = availability_from_workload(workload, "Setup", doubleheader=True)
        self.assertLess(result["availability_score"], 30)
        self.assertIn(result["availability_label"], {"Limited", "Unavailable"})
        self.assertIn("doubleheader", result["availability_reason"])

    def test_build_projected_bullpen_excludes_probable_starter_and_inactive(self):
        roster = pd.DataFrame(
            [
                {"player_id": 1, "Player": "Starter", "team_id": 100, "Position": "P", "group": "pitching", "status": "Active"},
                {"player_id": 2, "Player": "Closer", "team_id": 100, "Position": "P", "group": "pitching", "status": "Active"},
                {"player_id": 3, "Player": "Injured", "team_id": 100, "Position": "P", "group": "pitching", "status": "Injured list"},
            ]
        )
        stats = pd.DataFrame(
            [
                {"player_id": 1, "G": 10, "GS": 10},
                {"player_id": 2, "G": 30, "GS": 0, "SV": 12},
                {"player_id": 3, "G": 15, "GS": 0},
            ]
        )
        projected = build_projected_bullpen(
            roster,
            stats,
            probable_starter_id=1,
            game_date="2026-07-11",
            team_id=100,
        )
        names = {row["Player"] for row in projected}
        self.assertIn("Closer", names)
        self.assertIn("Injured", names)
        self.assertNotIn("Starter", names)
        injured = next(row for row in projected if row["Player"] == "Injured")
        self.assertTrue(injured["excluded_from_composite"])
        self.assertEqual(injured["availability_label"], "Unavailable")

    def test_appearance_probabilities_normalize(self):
        rows = normalize_appearance_probabilities(
            [
                {"projected_role": "Closer", "availability_score": 100},
                {"projected_role": "Setup", "availability_score": 50},
            ]
        )
        self.assertAlmostEqual(sum(row["appearance_probability"] for row in rows), 1.0, places=3)

    def test_composite_weights_likely_available_relievers(self):
        composite = composite_bullpen_matchup(
            [
                {
                    "Player": "Good Matchup",
                    "availability_label": "Available",
                    "availability_score": 100,
                    "appearance_probability": 0.8,
                    "expected_batters_faced_midpoint": 4,
                    "projected_role": "Setup",
                    "matchup_score": 70,
                    "projected_wOBA": 0.360,
                    "Direct PA": 20,
                },
                {
                    "Player": "Bad Limited",
                    "availability_label": "Limited",
                    "availability_score": 20,
                    "appearance_probability": 0.2,
                    "expected_batters_faced_midpoint": 3,
                    "projected_role": "Long Relief",
                    "matchup_score": 20,
                    "projected_wOBA": 0.260,
                    "Direct PA": 0,
                },
            ]
        )
        self.assertGreater(composite["overall_score"], 60)
        self.assertEqual(composite["most_favorable"], "Good Matchup")
        self.assertEqual(composite["most_difficult"], "Bad Limited")
        self.assertEqual(composite["confidence"], "Moderate")


if __name__ == "__main__":
    unittest.main()
