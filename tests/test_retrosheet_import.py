import csv
import tempfile
from pathlib import Path
import unittest
import zipfile

from backfill_database import parse_retrosheet_archive, synthetic_game_pk


def write_csv_to_zip(archive, name, fieldnames, rows):
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        newline="",
        delete=False,
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
        temp_path = Path(handle.name)
    try:
        archive.write(temp_path, arcname=name)
    finally:
        temp_path.unlink()


class RetrosheetImportTests(unittest.TestCase):
    def test_year_archive_maps_ids_and_aggregates_game_rows(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            archive_path = Path(temp_dir) / "2025csvs.zip"
            with zipfile.ZipFile(archive_path, "w") as archive:
                write_csv_to_zip(
                    archive,
                    "2025gameinfo.csv",
                    [
                        "gid",
                        "visteam",
                        "hometeam",
                        "date",
                        "gametype",
                    ],
                    [
                        {
                            "gid": "BOS202504010",
                            "visteam": "NYA",
                            "hometeam": "BOS",
                            "date": "20250401",
                            "gametype": "regular",
                        }
                    ],
                )
                write_csv_to_zip(
                    archive,
                    "2025plays.csv",
                    [
                        "gid",
                        "batter",
                        "pitcher",
                        "batteam",
                        "pitteam",
                        "nump",
                        "pa",
                        "ab",
                        "single",
                        "double",
                        "triple",
                        "hr",
                        "walk",
                        "hbp",
                        "k",
                        "rbi",
                        "sf",
                    ],
                    [
                        {
                            "gid": "BOS202504010",
                            "batter": "batte001",
                            "pitcher": "pitch001",
                            "batteam": "NYA",
                            "pitteam": "BOS",
                            "nump": "4",
                            "pa": "1",
                            "ab": "1",
                            "single": "0",
                            "double": "0",
                            "triple": "0",
                            "hr": "1",
                            "walk": "0",
                            "hbp": "0",
                            "k": "0",
                            "rbi": "2",
                            "sf": "0",
                        },
                        {
                            "gid": "BOS202504010",
                            "batter": "batte001",
                            "pitcher": "pitch001",
                            "batteam": "NYA",
                            "pitteam": "BOS",
                            "nump": "5",
                            "pa": "1",
                            "ab": "0",
                            "single": "0",
                            "double": "0",
                            "triple": "0",
                            "hr": "0",
                            "walk": "1",
                            "hbp": "0",
                            "k": "0",
                            "rbi": "0",
                            "sf": "0",
                        },
                    ],
                )
                write_csv_to_zip(
                    archive,
                    "2025pitching.csv",
                    [
                        "gid",
                        "id",
                        "team",
                        "stattype",
                        "gametype",
                        "p_gs",
                        "p_ipouts",
                        "p_bfp",
                        "p_h",
                        "p_w",
                        "p_hbp",
                        "p_k",
                        "p_hr",
                        "p_r",
                        "p_er",
                        "opp",
                    ],
                    [
                        {
                            "gid": "BOS202504010",
                            "id": "pitch001",
                            "team": "BOS",
                            "stattype": "value",
                            "gametype": "regular",
                            "p_gs": "1",
                            "p_ipouts": "18",
                            "p_bfp": "24",
                            "p_h": "5",
                            "p_w": "1",
                            "p_hbp": "0",
                            "p_k": "8",
                            "p_hr": "1",
                            "p_r": "2",
                            "p_er": "2",
                            "opp": "NYA",
                        }
                    ],
                )

            mapping = {
                "batte001": {
                    "player_id": 10,
                    "retro_id": "batte001",
                    "player_name": "Test Batter",
                },
                "pitch001": {
                    "player_id": 20,
                    "retro_id": "pitch001",
                    "player_name": "Test Pitcher",
                },
            }
            parsed = parse_retrosheet_archive(archive_path, 2025, mapping)

        self.assertEqual(len(parsed["games"]), 1)
        self.assertEqual(
            parsed["games"][0]["game_pk"],
            synthetic_game_pk("BOS202504010"),
        )
        self.assertEqual(parsed["games"][0]["away_team"], "New York Yankees")
        self.assertEqual(len(parsed["batter_pitcher_logs"]), 1)
        self.assertEqual(parsed["batter_pitcher_logs"][0]["PA"], 2)
        self.assertEqual(parsed["batter_pitcher_logs"][0]["HR"], 1)
        self.assertEqual(parsed["batter_pitcher_logs"][0]["TB"], 4)
        self.assertEqual(parsed["pitcher_logs"][0]["pitch_count"], 9)


if __name__ == "__main__":
    unittest.main()
