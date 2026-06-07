import unittest

import pandas as pd

from src.weather import (
    calculate_weather_adjustments,
    enrich_schedule_with_weather,
    field_wind_arrow,
    project_wind_to_field,
    weather_icon,
)


class WeatherTests(unittest.TestCase):
    def test_wind_is_projected_against_center_field_bearing(self):
        out_component, cross_component, label = project_wind_to_field(
            wind_speed_mph=10,
            wind_from_degrees=270,
            field_azimuth=90,
        )

        self.assertAlmostEqual(out_component, 10.0)
        self.assertAlmostEqual(cross_component, 0.0)
        self.assertEqual(label, "Out to CF")

    def test_open_park_weather_enriches_schedule_and_boosts_hitters(self):
        schedule = pd.DataFrame(
            [
                {
                    "game_time_utc": "2026-06-01T19:10:00Z",
                    "venue_latitude": 39.756,
                    "venue_longitude": -104.994,
                    "field_azimuth": 90.0,
                    "roof_type": "Open",
                }
            ]
        )

        def forecast_loader(latitude, longitude, forecast_date):
            self.assertEqual(forecast_date, "2026-06-01")
            return {
                "hourly": {
                    "time": ["2026-06-01T19:00"],
                    "temperature_2m": [85.0],
                    "relative_humidity_2m": [30],
                    "precipitation_probability": [5],
                    "surface_pressure": [835.0],
                    "wind_speed_10m": [10.0],
                    "wind_direction_10m": [270],
                    "wind_gusts_10m": [16.0],
                    "weather_code": [1],
                }
            }

        result = enrich_schedule_with_weather(schedule, forecast_loader)

        self.assertEqual(result.iloc[0]["wind_field_direction"], "Out to CF")
        self.assertGreater(result.iloc[0]["hitter_weather_adjustment"], 3.0)
        self.assertLess(result.iloc[0]["pitcher_weather_adjustment"], 0.0)
        self.assertIn("85 F", result.iloc[0]["weather_summary"])
        self.assertEqual(result.iloc[0]["weather_icon"], "partly-cloudy")
        self.assertEqual(result.iloc[0]["weather_display"], "85°")
        self.assertEqual(result.iloc[0]["wind_display"], "↑ 10")
        self.assertIn("up = out to center", result.iloc[0]["wind_tooltip"])

    def test_retractable_roof_is_projection_neutral(self):
        hitter_adjustment, pitcher_adjustment = calculate_weather_adjustments(
            out_component_mph=15,
            air_density=1.0,
            roof_type="Retractable",
        )

        self.assertEqual(hitter_adjustment, 0.0)
        self.assertEqual(pitcher_adjustment, 0.0)

    def test_compact_weather_symbols_are_field_relative(self):
        self.assertEqual(weather_icon("Thunderstorms"), "storm")
        self.assertEqual(weather_icon("Overcast"), "cloudy")
        self.assertEqual(field_wind_arrow("Out to CF"), "↑")
        self.assertEqual(field_wind_arrow("R to L"), "←")


if __name__ == "__main__":
    unittest.main()
