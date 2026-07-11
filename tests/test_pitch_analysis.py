import unittest

from src.pitch_analysis import (
    PITCH_CODE_MAP,
    calculate_batting_rates,
    calculate_pitch_type_summaries,
    direct_bvp_summary,
    evidence_blend,
    ordered_pitch_sequence,
    pitch_name_for_code,
    plate_appearance_logs_from_pitches,
    sample_size_label,
    shrink_rate,
)


class PitchAnalysisTests(unittest.TestCase):
    def test_supported_pitch_codes_have_readable_names(self):
        expected = {
            "FF": "Four-Seam Fastball",
            "SI": "Sinker",
            "FT": "Two-Seam Fastball",
            "FC": "Cutter",
            "SL": "Slider",
            "ST": "Sweeper",
            "SV": "Slurve",
            "CU": "Curveball",
            "KC": "Knuckle Curve",
            "CS": "Slow Curve",
            "CH": "Changeup",
            "FS": "Split-Finger",
            "FO": "Forkball",
            "KN": "Knuckleball",
            "SC": "Screwball",
            "EP": "Eephus",
            "FA": "Generic Fastball",
        }
        self.assertEqual(PITCH_CODE_MAP, expected)
        for code, name in expected.items():
            self.assertEqual(pitch_name_for_code(code), name)

    def test_unknown_pitch_code_is_safe(self):
        self.assertEqual(
            pitch_name_for_code("XX"),
            "Unknown or Unclassified (XX)",
        )
        self.assertEqual(pitch_name_for_code(None), "Unknown or Unclassified")

    def test_pitch_sequence_ordering(self):
        rows = [
            {"game_date": "2026-07-02", "game_pk": 2, "at_bat_number": 1, "pitch_number": 2},
            {"game_date": "2026-07-01", "game_pk": 1, "at_bat_number": 2, "pitch_number": 1},
            {"game_date": "2026-07-02", "game_pk": 2, "at_bat_number": 1, "pitch_number": 1},
        ]
        ordered = ordered_pitch_sequence(rows)
        self.assertEqual([row["pitch_number"] for row in ordered], [1, 1, 2])

    def test_plate_appearance_grouping_and_dedup_shape(self):
        rows = [
            {
                "game_pk": 10,
                "game_date": "2026-07-01",
                "at_bat_number": 3,
                "pitch_number": 2,
                "batter_id": 1,
                "pitcher_id": 2,
                "pitch_type": "SL",
                "balls": 0,
                "strikes": 1,
                "event": "single",
                "inning": 1,
            },
            {
                "game_pk": 10,
                "game_date": "2026-07-01",
                "at_bat_number": 3,
                "pitch_number": 1,
                "batter_id": 1,
                "pitcher_id": 2,
                "pitch_type": "ST",
                "balls": 0,
                "strikes": 0,
                "inning": 1,
            },
        ]
        logs = plate_appearance_logs_from_pitches(rows)
        self.assertEqual(len(logs), 1)
        self.assertEqual(logs[0]["pitch_sequence"], "ST SL")
        self.assertEqual(logs[0]["event"], "single")
        self.assertEqual(logs[0]["pitch_count"], 2)

    def test_batting_rates_and_division_by_zero(self):
        rates = calculate_batting_rates(
            {"PA": 10, "AB": 8, "H": 4, "2B": 1, "3B": 0, "HR": 1, "BB": 1, "HBP": 1, "SF": 0, "SO": 2}
        )
        self.assertEqual(rates["AVG"], 0.5)
        self.assertEqual(rates["SLG"], 1.0)
        self.assertAlmostEqual(rates["OBP"], 0.6)
        self.assertIsNone(calculate_batting_rates({"AB": 0})["AVG"])

    def test_direct_summary_sample_labels_and_woba(self):
        summary = direct_bvp_summary(
            {"PA": 4, "AB": 3, "H": 1, "2B": 0, "3B": 0, "HR": 1, "BB": 1, "SO": 1},
            [{"game_date": "2026-06-01"}, {"game_date": "2026-07-01"}],
        )
        self.assertEqual(summary["sample_label"], "Very limited")
        self.assertEqual(summary["data_date_range"], "2026-06-01 to 2026-07-01")
        self.assertIsNotNone(summary["wOBA"])
        self.assertEqual(sample_size_label(50), "Stronger sample")

    def test_pitch_type_summary_keeps_sweeper_and_slider_separate(self):
        rows = [
            {
                "pitch_type": "ST",
                "release_speed": 84,
                "release_spin_rate": 2500,
                "zone": 14,
                "pitch_description": "swinging_strike",
            },
            {
                "pitch_type": "SL",
                "release_speed": 86,
                "release_spin_rate": 2400,
                "zone": 5,
                "pitch_description": "called_strike",
                "event": "strikeout",
            },
        ]
        summaries = calculate_pitch_type_summaries(rows)
        self.assertEqual({row["pitch_type"] for row in summaries}, {"ST", "SL"})
        self.assertTrue(all(row["pitch_count"] == 1 for row in summaries))

    def test_small_sample_shrinkage_and_evidence_blend(self):
        self.assertAlmostEqual(shrink_rate(1.0, 1, 0.300, 9), 0.370)
        blended = evidence_blend(
            direct=0.600,
            direct_pa=2,
            hand_split=0.340,
            hand_pa=80,
            baseline=0.315,
        )
        self.assertLess(blended, 0.360)
        self.assertGreater(blended, 0.315)


if __name__ == "__main__":
    unittest.main()
