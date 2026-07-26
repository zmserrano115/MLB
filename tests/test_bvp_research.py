import unittest
from unittest.mock import patch

import pandas as pd

from src.bvp_research import (
    _game_log_needs_pitch_backfill,
    exact_pitch_comparison_rows,
    game_context,
    game_options,
    opponent_context_for_batter,
    player_search_options,
    scheduled_game_pks_for_player,
    specific_pitcher_research,
    team_record_from_game_context,
)


class BvpResearchTests(unittest.TestCase):
    def test_partial_game_pitch_history_is_backfilled(self):
        stored = {123: {4}}
        self.assertTrue(
            _game_log_needs_pitch_backfill(
                {"game_pk": 123, "PA": 3},
                stored,
            )
        )
        self.assertFalse(
            _game_log_needs_pitch_backfill(
                {"game_pk": 123, "PA": 1},
                stored,
            )
        )

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
        self.assertNotIn("123", next(iter(game_options(schedule))))
        self.assertNotIn("99", next(iter(player_search_options(players))))

    def test_exact_pitch_rows_use_repertoire_as_empty_scaffold(self):
        overall_mix = [{"pitch_code": "FF", "COUNT": 500, "PERCENTAGE": 55.0}]
        empty_rows = exact_pitch_comparison_rows([], overall_mix)
        self.assertEqual([row["Code"] for row in empty_rows], ["FF"])
        self.assertIsNone(empty_rows[0]["Direct Count"])
        rows = exact_pitch_comparison_rows(
            [{"pitch_type": "SL", "pitch_count": 7, "wOBA": 0.250}],
            overall_mix,
        )
        self.assertEqual([row["Code"] for row in rows], ["FF", "SL"])
        slider = next(row for row in rows if row["Code"] == "SL")
        self.assertEqual(slider["Direct Count"], 7)

    def test_exact_pitch_rows_keep_standard_scaffold_when_all_sources_are_empty(self):
        rows = exact_pitch_comparison_rows([], [])

        self.assertEqual(
            [row["Code"] for row in rows],
            ["FF", "SI", "FC", "SL", "CU", "CH", "FS", "ST"],
        )
        self.assertTrue(all(row["Direct Count"] is None for row in rows))

    def test_selected_player_single_game_is_inferred(self):
        schedule = pd.DataFrame(
            [
                {
                    "game_pk": 123,
                    "away_team_id": 147,
                    "home_team_id": 111,
                    "away_probable_pitcher_id": 7,
                },
                {
                    "game_pk": 456,
                    "away_team_id": 119,
                    "home_team_id": 135,
                },
            ]
        )
        self.assertEqual(
            scheduled_game_pks_for_player(
                schedule,
                {"player_id": 99, "team_id": 147},
            ),
            [123],
        )
        self.assertEqual(
            scheduled_game_pks_for_player(
                schedule,
                {"player_id": 7},
            ),
            [123],
        )

    @patch("src.bvp_research.save_pitch_events")
    @patch("src.bvp_research.fetch_matchup_pitch_events")
    @patch("src.bvp_research.database.get_pitcher_pitch_type_stats_from_db")
    @patch("src.bvp_research.database.get_pitch_level_events_for_matchup")
    @patch("src.bvp_research.database.get_batter_vs_pitcher_game_logs_from_db")
    @patch("src.bvp_research.database.get_batter_vs_pitcher_stats_from_db")
    def test_specific_research_backfills_missing_career_games(
        self,
        direct_stats,
        game_logs,
        stored_events,
        pitcher_mix,
        fetch_events,
        save_events,
    ):
        direct_stats.return_value = {"matchup_grade": "Neutral", "PA": 2, "AB": 2}
        game_logs.return_value = [
            {"game_pk": 1, "game_date": "2024-06-01", "season": 2024},
            {"game_pk": 2, "game_date": "2025-06-01", "season": 2025},
        ]
        stored_events.return_value = [
            {
                "game_pk": 1,
                "game_date": "2024-06-01",
                "season": 2024,
                "at_bat_number": 1,
                "pitch_number": 1,
                "batter_id": 10,
                "pitcher_id": 20,
                "pitch_type": "FF",
                "pitch_description": "hit_into_play",
                "event": "field_out",
            }
        ]
        fetch_events.return_value = [
            {
                "game_pk": 2,
                "game_date": "2025-06-01",
                "season": 2025,
                "at_bat_number": 2,
                "pitch_number": 1,
                "batter_id": 10,
                "pitcher_id": 20,
                "pitch_type": "SL",
                "pitch_description": "hit_into_play",
                "event": "single",
            }
        ]
        pitcher_mix.return_value = [{"pitch_code": "FF", "COUNT": 100}]

        result = specific_pitcher_research(
            10,
            20,
            2026,
            backfill_missing=True,
        )

        stored_events.assert_called_once_with(10, 20, None)
        fetch_events.assert_called_once_with(10, 20, [game_logs.return_value[1]])
        save_events.assert_called_once_with(fetch_events.return_value)
        self.assertEqual(len(result["plate_appearances"]), 2)
        self.assertEqual(
            {row["Code"] for row in result["comparison_rows"]},
            {"FF", "SL"},
        )

    @patch("src.bvp_research.fetch_matchup_pitch_events")
    @patch("src.bvp_research.database.get_pitcher_pitch_type_stats_from_db")
    @patch("src.bvp_research.database.get_pitch_level_events_for_matchup")
    @patch("src.bvp_research.database.get_batter_vs_pitcher_game_logs_from_db")
    @patch("src.bvp_research.database.get_batter_vs_pitcher_stats_from_db")
    def test_specific_research_defers_missing_history_network_work(
        self,
        direct_stats,
        game_logs,
        stored_events,
        pitcher_mix,
        fetch_events,
    ):
        direct_stats.return_value = {"matchup_grade": "Neutral", "PA": 1, "AB": 1}
        game_logs.return_value = [
            {"game_pk": 123, "game_date": "2025-06-01", "PA": 1}
        ]
        stored_events.return_value = []
        pitcher_mix.return_value = []

        result = specific_pitcher_research(10, 20, 2026)

        fetch_events.assert_not_called()
        self.assertEqual(result["missing_pitch_game_logs"], game_logs.return_value)
        self.assertEqual(len(result["comparison_rows"]), 8)

    @patch("src.bvp_research.database.get_pitcher_pitch_type_stats_from_db")
    @patch("src.bvp_research.database.get_pitch_level_events_for_matchup")
    @patch("src.bvp_research.database.get_batter_vs_pitcher_game_logs_from_db")
    @patch("src.bvp_research.database.get_batter_vs_pitcher_stats_from_db")
    def test_specific_research_uses_transient_cloud_backfill_events(
        self,
        direct_stats,
        game_logs,
        stored_events,
        pitcher_mix,
    ):
        direct_stats.return_value = {"matchup_grade": "Neutral", "PA": 1, "AB": 1}
        game_logs.return_value = [
            {"game_pk": -123, "game_date": "2025-06-01", "PA": 1}
        ]
        stored_events.return_value = []
        pitcher_mix.return_value = []
        fetched_events = [
            {
                "game_pk": 777,
                "game_date": "2025-06-01",
                "season": 2025,
                "at_bat_number": 4,
                "pitch_number": 1,
                "batter_id": 10,
                "pitcher_id": 20,
                "pitch_type": "FF",
                "pitch_description": "called_strike",
                "event": "strikeout",
            }
        ]

        result = specific_pitcher_research(
            10,
            20,
            2026,
            supplemental_pitch_events=fetched_events,
        )

        self.assertEqual(result["pitch_source"], "MLB StatsAPI game feeds")
        self.assertEqual(result["pitch_events"], fetched_events)
        self.assertEqual(result["missing_pitch_game_logs"], [])
        self.assertEqual(result["comparison_rows"][0]["Code"], "FF")
        self.assertEqual(result["comparison_rows"][0]["Direct Count"], 1)

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
