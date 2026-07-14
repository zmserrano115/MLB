from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, date, datetime
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from all_rise.domain.weather import (
    calculate_air_density,
    calculate_weather_adjustments,
    project_wind_to_field,
    weather_edge_label,
)
from all_rise.jobs import QualityGateError, RetryableTaskError
from sqlalchemy import create_engine, text

MLB_SCHEDULE_URL = "https://statsapi.mlb.com/api/v1/schedule"
MLB_LIVE_FEED_URL = "https://statsapi.mlb.com/api/v1.1/game/{game_pk}/feed/live"
OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"


class JsonHttpClient:
    def get(self, url: str, params: Mapping[str, Any], *, provider: str) -> dict[str, Any]:
        request = Request(
            f"{url}?{urlencode(params)}",
            headers={"Accept": "application/json", "User-Agent": "AllRiseAnalytics/1.0"},
        )
        try:
            with urlopen(request, timeout=20) as response:  # noqa: S310 - fixed provider URLs
                payload = json.load(response)
        except HTTPError as exc:
            raise RetryableTaskError(f"{provider} returned HTTP {exc.code}") from exc
        except (URLError, TimeoutError, OSError) as exc:
            raise RetryableTaskError(f"{provider} request failed: {exc}") from exc
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise QualityGateError(f"{provider} returned malformed JSON") from exc
        if not isinstance(payload, dict):
            raise QualityGateError(f"{provider} returned a non-object response")
        return payload


class MlbScheduleProvider:
    def __init__(
        self, http: JsonHttpClient | None = None, *, base_url: str = MLB_SCHEDULE_URL
    ) -> None:
        self._http = http or JsonHttpClient()
        self._base_url = base_url

    def fetch(self, game_date: str, source_version: str) -> list[dict[str, Any]]:
        payload = self._http.get(
            self._base_url,
            {
                "sportId": 1,
                "date": game_date,
                "hydrate": "probablePitcher(note),team,venue(location,fieldInfo),linescore",
            },
            provider="MLB StatsAPI",
        )
        records: list[dict[str, Any]] = []
        for day in payload.get("dates", []):
            for game in day.get("games", []):
                records.append(_schedule_record(game, game_date, source_version))
        return records


class MlbLiveFeedProvider:
    def __init__(
        self, http: JsonHttpClient | None = None, *, base_url: str = MLB_LIVE_FEED_URL
    ) -> None:
        self._http = http or JsonHttpClient()
        self._base_url = base_url

    def fetch(self, game_pk: int) -> dict[str, Any]:
        return self._http.get(
            self._base_url.format(game_pk=game_pk),
            {},
            provider="MLB StatsAPI live feed",
        )


def _schedule_record(
    game: Mapping[str, Any], game_date: str, source_version: str
) -> dict[str, Any]:
    teams = _mapping(game.get("teams"))
    away = _mapping(teams.get("away"))
    home = _mapping(teams.get("home"))
    away_team = _mapping(away.get("team"))
    home_team = _mapping(home.get("team"))
    venue = _mapping(game.get("venue"))
    location = _mapping(venue.get("location"))
    coordinates = _mapping(location.get("defaultCoordinates"))
    field_info = _mapping(venue.get("fieldInfo"))
    status = _mapping(game.get("status"))
    game_pk = game.get("gamePk")
    return {
        "source_game_id": f"mlb:{game_pk}" if game_pk is not None else None,
        "mlb_game_pk": game_pk,
        "game_date": game_date,
        "season": int(game.get("season") or date.fromisoformat(game_date).year),
        "game_time_utc": game.get("gameDate"),
        "game_status": status.get("detailedState") or status.get("abstractGameState"),
        "away_score": away.get("score"),
        "home_score": home.get("score"),
        "away_team": {
            "provider_team_id": away_team.get("id"),
            "name": away_team.get("name"),
            "abbreviation": away_team.get("abbreviation"),
        },
        "home_team": {
            "provider_team_id": home_team.get("id"),
            "name": home_team.get("name"),
            "abbreviation": home_team.get("abbreviation"),
        },
        "away_probable_pitcher": _pitcher(away.get("probablePitcher")),
        "home_probable_pitcher": _pitcher(home.get("probablePitcher")),
        "venue": {
            "provider_venue_id": venue.get("id"),
            "name": venue.get("name"),
            "city": location.get("city"),
            "latitude": coordinates.get("latitude"),
            "longitude": coordinates.get("longitude"),
            "elevation_ft": location.get("elevation"),
            "roof_type": field_info.get("roofType"),
            "center_field_azimuth": location.get("azimuthAngle"),
        },
        "source_version": source_version,
    }


def _pitcher(value: Any) -> dict[str, Any] | None:
    pitcher = _mapping(value)
    if pitcher.get("id") is None:
        return None
    return {"provider_player_id": pitcher["id"], "name": pitcher.get("fullName")}


class PostgresWeatherCandidates:
    def __init__(self, database_url: str) -> None:
        self._database_url = database_url

    def fetch(self, start: str, end: str) -> list[dict[str, Any]]:
        engine = create_engine(self._database_url, pool_pre_ping=True)
        try:
            with engine.connect() as connection:
                rows = connection.execute(
                    text(
                        """
                        SELECT g.source_game_id, g.game_date, g.game_time_utc,
                               v.latitude, v.longitude, v.elevation_ft,
                               v.roof_type, v.center_field_azimuth
                        FROM games g
                        LEFT JOIN venues v ON v.id = g.venue_id
                        WHERE g.game_date BETWEEN :start AND :end
                        ORDER BY g.game_date, g.game_time_utc, g.source_game_id
                        """
                    ),
                    {"start": date.fromisoformat(start), "end": date.fromisoformat(end)},
                )
                return [dict(row._mapping) for row in rows]
        finally:
            engine.dispose()


class OpenMeteoProvider:
    def __init__(
        self, http: JsonHttpClient | None = None, *, base_url: str = OPEN_METEO_URL
    ) -> None:
        self._http = http or JsonHttpClient()
        self._base_url = base_url
        self._cache: dict[tuple[float, float, str], dict[str, Any]] = {}

    def forecast(self, candidate: Mapping[str, Any]) -> dict[str, Any]:
        game_date = _game_date(candidate)
        latitude = _float(candidate.get("latitude"))
        longitude = _float(candidate.get("longitude"))
        if latitude is None or longitude is None:
            raise QualityGateError(
                f"missing venue coordinates for {candidate.get('source_game_id')}"
            )
        key = (round(latitude, 6), round(longitude, 6), game_date)
        payload = self._cache.get(key)
        if payload is None:
            payload = self._http.get(
                self._base_url,
                {
                    "latitude": latitude,
                    "longitude": longitude,
                    "start_date": game_date,
                    "end_date": game_date,
                    "timezone": "UTC",
                    "temperature_unit": "fahrenheit",
                    "wind_speed_unit": "mph",
                    "hourly": (
                        "temperature_2m,apparent_temperature,relative_humidity_2m,"
                        "precipitation_probability,surface_pressure,wind_speed_10m,"
                        "wind_direction_10m,weather_code"
                    ),
                },
                provider="Open-Meteo",
            )
            self._cache[key] = payload
        return _forecast_record(payload, candidate)


def _forecast_record(payload: Mapping[str, Any], candidate: Mapping[str, Any]) -> dict[str, Any]:
    hourly = _mapping(payload.get("hourly"))
    raw_times = hourly.get("time")
    if not isinstance(raw_times, list) or not raw_times:
        raise QualityGateError("Open-Meteo response contains no hourly forecast")
    times = [_utc(value) for value in raw_times]
    target = _utc(candidate.get("game_time_utc") or f"{_game_date(candidate)}T19:00:00Z")
    index = min(range(len(times)), key=lambda item: abs((times[item] - target).total_seconds()))
    forecast_for = times[index]
    temperature = _number_at(hourly, "temperature_2m", index)
    feels_like = _number_at(hourly, "apparent_temperature", index)
    humidity = _number_at(hourly, "relative_humidity_2m", index)
    precipitation = _number_at(hourly, "precipitation_probability", index)
    pressure = _number_at(hourly, "surface_pressure", index)
    wind_speed = _number_at(hourly, "wind_speed_10m", index)
    wind_direction = _number_at(hourly, "wind_direction_10m", index)
    weather_code = _number_at(hourly, "weather_code", index)
    wind_out, wind_cross, field_direction = project_wind_to_field(
        wind_speed, wind_direction, candidate.get("center_field_azimuth")
    )
    air_density = calculate_air_density(temperature, humidity, pressure)
    hitter, pitcher = calculate_weather_adjustments(
        wind_out, air_density, candidate.get("roof_type")
    )
    return {
        "forecast_for": forecast_for.isoformat(),
        "condition": _condition(weather_code),
        "temperature_f": temperature,
        "feels_like_f": feels_like,
        "humidity_percent": humidity,
        "wind_speed_mph": wind_speed,
        "wind_direction_degrees": wind_direction,
        "wind_out_mph": wind_out,
        "precipitation_probability": precipitation,
        "hitter_adjustment": hitter,
        "pitcher_adjustment": pitcher,
        "edge_label": weather_edge_label(hitter, candidate.get("roof_type")),
        "stale": abs((forecast_for - target).total_seconds()) > 5_400,
        "provider_residual": {
            "weather_code": int(weather_code) if weather_code is not None else None,
            "surface_pressure_hpa": pressure,
            "air_density_kg_m3": air_density,
            "wind_cross_mph": wind_cross,
            "wind_field_direction": field_direction,
        },
    }


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _game_date(candidate: Mapping[str, Any]) -> str:
    value = candidate.get("game_date")
    return value.isoformat() if isinstance(value, date) else str(value)


def _utc(value: Any) -> datetime:
    result = (
        value
        if isinstance(value, datetime)
        else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    )
    return result.replace(tzinfo=UTC) if result.tzinfo is None else result.astimezone(UTC)


def _float(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _number_at(hourly: Mapping[str, Any], name: str, index: int) -> float | None:
    values = hourly.get(name)
    if not isinstance(values, list) or index >= len(values):
        return None
    return _float(values[index])


def _condition(code: float | None) -> str:
    value = int(code) if code is not None else -1
    if value == 0:
        return "Clear"
    if value in {1, 2}:
        return "Partly cloudy"
    if value == 3:
        return "Overcast"
    if value in {45, 48}:
        return "Fog"
    if value in {51, 53, 55, 56, 57}:
        return "Drizzle"
    if value in {61, 63, 65, 66, 67, 80, 81, 82}:
        return "Rain"
    if value in {71, 73, 75, 77, 85, 86}:
        return "Snow"
    if value in {95, 96, 99}:
        return "Thunderstorms"
    return "Unknown"
