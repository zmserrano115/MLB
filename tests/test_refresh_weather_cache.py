import unittest
from unittest.mock import patch

import pandas as pd

from refresh_weather_cache import build_weather_cache


class RefreshWeatherCacheTests(unittest.TestCase):
    @patch("refresh_weather_cache.enrich_schedule_with_weather")
    @patch("refresh_weather_cache.get_daily_schedule")
    def test_cache_contains_published_game_weather(
        self,
        mock_schedule,
        mock_enrich,
    ):
        mock_schedule.return_value = pd.DataFrame(
            [{"game_pk": 123, "game_date": "2026-06-08"}]
        )
        mock_enrich.return_value = pd.DataFrame(
            [
                {
                    "game_pk": 123,
                    "game_date": "2026-06-08",
                    "weather_status": "Forecast available",
                    "weather_source": "Open-Meteo",
                    "temperature_f": 78.0,
                }
            ]
        )

        payload = build_weather_cache(
            pd.Timestamp("2026-06-08").date(),
            days=1,
        )

        self.assertEqual(payload["start_date"], "2026-06-08")
        self.assertEqual(len(payload["records"]), 1)
        self.assertEqual(payload["records"][0]["game_pk"], 123)
        self.assertEqual(
            payload["records"][0]["weather_status"],
            "Forecast available",
        )


if __name__ == "__main__":
    unittest.main()
