import unittest
from unittest.mock import Mock, patch

import pandas as pd
import requests

from src.weather import (
    calculate_weather_adjustments,
    convert_mlb_game_weather,
    convert_met_forecast,
    enrich_schedule_with_weather,
    fetch_hourly_forecast,
    fetch_hourly_forecasts,
    field_wind_arrow,
    merge_cached_weather,
    preserve_previous_weather,
    project_wind_to_field,
    weather_icon,
)


def forecast_payload(forecast_time):
    return {
        "hourly": {
            "time": [forecast_time],
            "temperature_2m": [75.0],
            "relative_humidity_2m": [50.0],
            "precipitation_probability": [5.0],
            "surface_pressure": [1000.0],
            "wind_speed_10m": [8.0],
            "wind_direction_10m": [180.0],
            "wind_gusts_10m": [12.0],
            "weather_code": [1],
        }
    }


class WeatherTests(unittest.TestCase):
    @patch("src.weather.requests.get")
    def test_slate_forecasts_use_one_batched_request(self, mock_get):
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = [
            forecast_payload("2026-06-08T19:00"),
            forecast_payload("2026-06-08T20:00"),
        ]
        mock_get.return_value = response
        locations = [(39.7, -104.9), (33.8, -117.9)]

        result = fetch_hourly_forecasts(
            locations,
            "2026-06-08",
            "2026-06-09",
        )

        self.assertEqual(mock_get.call_count, 1)
        self.assertEqual(set(result), set(locations))
        params = mock_get.call_args.kwargs["params"]
        self.assertEqual(params["latitude"], "39.7,33.8")
        self.assertEqual(params["start_date"], "2026-06-08")
        self.assertEqual(params["end_date"], "2026-06-09")

    def test_met_forecast_converts_to_shared_weather_schema(self):
        payload = {
            "properties": {
                "timeseries": [
                    {
                        "time": "2026-06-08T19:00:00Z",
                        "data": {
                            "instant": {
                                "details": {
                                    "air_pressure_at_sea_level": 1015.0,
                                    "air_temperature": 25.0,
                                    "cloud_area_fraction": 5.0,
                                    "relative_humidity": 50.0,
                                    "wind_from_direction": 180.0,
                                    "wind_speed": 4.0,
                                }
                            },
                            "next_1_hours": {
                                "summary": {"symbol_code": "clearsky_day"},
                                "details": {"precipitation_amount": 0.0},
                            },
                        },
                    }
                ]
            }
        }

        result = convert_met_forecast(payload, elevation_ft=0)

        self.assertEqual(result["weather_source"], "MET Norway")
        self.assertEqual(result["hourly"]["time"], ["2026-06-08T19:00:00Z"])
        self.assertAlmostEqual(result["hourly"]["temperature_2m"][0], 77.0)
        self.assertAlmostEqual(result["hourly"]["wind_speed_10m"][0], 8.947744)
        self.assertEqual(result["hourly"]["weather_code"][0], 0)

    def test_mlb_game_weather_converts_to_shared_weather_schema(self):
        game = {
            "game_pk": 123,
            "game_time_utc": "2026-06-08T19:10:00Z",
            "venue_elevation_ft": 100,
            "roof_type": "Open",
        }

        result = convert_mlb_game_weather(
            game,
            {
                "condition": "Partly Cloudy",
                "temp": "81",
                "wind": "12 mph, Out To RF",
            },
        )

        self.assertEqual(result["weather_source"], "MLB StatsAPI")
        self.assertEqual(result["weather_status"], "Forecast available")
        self.assertEqual(result["weather_condition"], "Partly Cloudy")
        self.assertEqual(result["wind_speed_mph"], 12.0)
        self.assertEqual(result["wind_field_direction"], "Out to CF")
        self.assertGreater(result["hitter_weather_adjustment"], 0.0)

    def test_published_cache_replaces_unavailable_runtime_weather(self):
        current = pd.DataFrame(
            [
                {
                    "game_pk": 123,
                    "weather_status": "Forecast unavailable",
                    "weather_display": "N/A",
                    "weather_icon": "unknown",
                }
            ]
        )
        cached = pd.DataFrame(
            [
                {
                    "game_pk": 123,
                    "weather_status": "Forecast available",
                    "weather_source": "Open-Meteo",
                    "weather_display": "79",
                    "weather_icon": "clear",
                    "temperature_f": 79.0,
                    "humidity_pct": 42.0,
                    "wind_speed_mph": 9.0,
                    "weather_edge": "Hitter boost",
                }
            ]
        )

        result = merge_cached_weather(current, cached)

        self.assertEqual(result.iloc[0]["weather_status"], "Forecast available")
        self.assertEqual(result.iloc[0]["weather_display"], "79")
        self.assertEqual(result.iloc[0]["weather_icon"], "clear")
        self.assertEqual(result.iloc[0]["humidity_pct"], 42.0)
        self.assertEqual(result.iloc[0]["wind_speed_mph"], 9.0)

    @patch("src.weather.fetch_met_forecast")
    @patch("src.weather.fetch_hourly_forecasts")
    def test_enrichment_falls_back_to_met_when_primary_fails(
        self,
        mock_open_meteo,
        mock_met,
    ):
        mock_open_meteo.side_effect = requests.ConnectionError("blocked")
        fallback = forecast_payload("2026-06-08T19:00")
        fallback["weather_source"] = "MET Norway"
        mock_met.return_value = fallback
        schedule = pd.DataFrame(
            [
                {
                    "game_time_utc": "2026-06-08T19:10:00Z",
                    "venue_latitude": 39.756,
                    "venue_longitude": -104.994,
                    "venue_elevation_ft": 5200,
                    "field_azimuth": 90.0,
                    "roof_type": "Open",
                }
            ]
        )

        result = enrich_schedule_with_weather(schedule)

        self.assertEqual(result.iloc[0]["weather_status"], "Forecast available")
        self.assertEqual(result.iloc[0]["weather_source"], "MET Norway")
        self.assertTrue(str(result.iloc[0]["weather_display"]).startswith("75"))
        self.assertEqual(mock_met.call_count, 1)

    @patch("src.weather.time.sleep")
    @patch("src.weather.requests.get")
    def test_forecast_retries_transient_request_errors(self, mock_get, mock_sleep):
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = forecast_payload("2026-06-08T19:00")
        mock_get.side_effect = [
            requests.ConnectionError("temporary"),
            response,
        ]

        result = fetch_hourly_forecast(39.7, -104.9, "2026-06-08")

        self.assertEqual(result, forecast_payload("2026-06-08T19:00"))
        self.assertEqual(mock_get.call_count, 2)
        mock_sleep.assert_called_once()

    @patch("src.weather.requests.get")
    def test_forecast_rejects_incomplete_provider_payload(self, mock_get):
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {"hourly": {"time": []}}
        mock_get.return_value = response

        with self.assertRaisesRegex(ValueError, "no hourly forecast"):
            fetch_hourly_forecast(
                39.7,
                -104.9,
                "2026-06-08",
                attempts=1,
            )

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

    def test_empty_forecast_keeps_complete_weather_columns(self):
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

        result = enrich_schedule_with_weather(
            schedule,
            lambda latitude, longitude, forecast_date: {"hourly": {"time": []}},
        )

        self.assertEqual(result.iloc[0]["weather_status"], "Forecast unavailable")
        self.assertEqual(result.iloc[0]["weather_condition"], "Unavailable")
        self.assertEqual(result.iloc[0]["weather_icon"], "unknown")
        self.assertEqual(result.iloc[0]["weather_display"], "N/A")
        self.assertEqual(result.iloc[0]["weather_edge"], "Neutral")
        self.assertEqual(result.iloc[0]["hitter_weather_adjustment"], 0.0)

    def test_previous_successful_forecast_survives_transient_failure(self):
        previous = pd.DataFrame(
            [
                {
                    "game_pk": 123,
                    "weather_status": "Forecast available",
                    "weather_condition": "Clear",
                    "weather_icon": "clear",
                    "weather_display": "78°",
                    "temperature_f": 78.0,
                    "wind_speed_mph": 8.0,
                    "weather_edge": "Hitter boost",
                    "hitter_weather_adjustment": 1.5,
                }
            ]
        )
        current = pd.DataFrame(
            [
                {
                    "game_pk": 123,
                    "weather_status": "Forecast unavailable",
                    "weather_condition": "Unavailable",
                    "weather_icon": "unknown",
                    "weather_display": "N/A",
                    "temperature_f": None,
                    "wind_speed_mph": None,
                    "weather_edge": "Neutral",
                    "hitter_weather_adjustment": 0.0,
                }
            ]
        )

        result = preserve_previous_weather(current, previous)

        self.assertEqual(result.iloc[0]["weather_status"], "Forecast available")
        self.assertEqual(result.iloc[0]["weather_display"], "78°")
        self.assertEqual(result.iloc[0]["wind_speed_mph"], 8.0)
        self.assertEqual(
            result.iloc[0]["weather_source"],
            "Last successful forecast",
        )

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
