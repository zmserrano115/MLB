import tempfile
from pathlib import Path
import unittest

import pandas as pd

from src import database
from src.pitch_data import (
    bvp_pitch_type_summary_rows,
    plate_sequence_rows,
    statcast_frame_to_pitch_events,
)


class PitchDataTests(unittest.TestCase):
    def setUp(self):
        self.original_db_path = database.DB_PATH
        self.original_initialized_path = database._INITIALIZED_PATH
        self.temp_dir = tempfile.TemporaryDirectory()
        database.DB_PATH = Path(self.temp_dir.name) / "test.db"
        database._INITIALIZED_PATH = None
        database.init_database()

    def tearDown(self):
        database.DB_PATH = self.original_db_path
        database._INITIALIZED_PATH = self.original_initialized_path
        self.temp_dir.cleanup()

    def test_statcast_frame_normalizes_and_deduplicates_events(self):
        frame = pd.DataFrame(
            [
                {
                    "game_pk": 1,
                    "game_date": "2026-07-01",
                    "at_bat_number": 2,
                    "pitch_number": 1,
                    "batter": 10,
                    "pitcher": 20,
                    "pitch_type": "XX",
                    "release_speed": 91.5,
                    "description": "called_strike",
                },
                {
                    "game_pk": 1,
                    "game_date": "2026-07-01",
                    "at_bat_number": 2,
                    "pitch_number": 1,
                    "batter": 10,
                    "pitcher": 20,
                    "pitch_type": "XX",
                    "release_speed": 92.5,
                    "description": "called_strike",
                },
            ]
        )
        events = statcast_frame_to_pitch_events(frame)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["pitch_type"], "XX")
        self.assertEqual(events[0]["pitch_name"], "Unknown or Unclassified (XX)")
        self.assertEqual(events[0]["release_speed"], 92.5)

    def test_plate_sequences_and_bvp_pitch_type_summaries(self):
        events = [
            {
                "game_pk": 1,
                "game_date": "2026-07-01",
                "season": 2026,
                "at_bat_number": 2,
                "pitch_number": 1,
                "batter_id": 10,
                "pitcher_id": 20,
                "pitch_type": "FF",
                "pitch_description": "foul",
                "balls": 0,
                "strikes": 0,
            },
            {
                "game_pk": 1,
                "game_date": "2026-07-01",
                "season": 2026,
                "at_bat_number": 2,
                "pitch_number": 2,
                "batter_id": 10,
                "pitcher_id": 20,
                "pitch_type": "FF",
                "pitch_description": "hit_into_play",
                "event": "double",
                "balls": 0,
                "strikes": 1,
                "launch_speed": 101,
            },
        ]
        sequences = plate_sequence_rows(events)
        self.assertEqual(len(sequences), 1)
        self.assertEqual(sequences[0]["pitch_sequence"], "FF FF")
        self.assertEqual(sequences[0]["pa_result"], "double")

        summaries = bvp_pitch_type_summary_rows(events)
        self.assertEqual(len(summaries), 1)
        self.assertEqual(summaries[0]["pitch_type"], "FF")
        self.assertEqual(summaries[0]["AVG"], 1.0)
        self.assertEqual(summaries[0]["SLG"], 2.0)


if __name__ == "__main__":
    unittest.main()
