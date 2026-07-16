"""Pure weather normalization and run-environment calculations."""

from __future__ import annotations

import math
from datetime import UTC, datetime
from typing import Any

import pandas as pd

WEATHER_VALUE_COLUMNS = (
    "forecast_time_utc",
    "temperature_f",
    "humidity_pct",
    "precip_probability_pct",
    "surface_pressure_hpa",
    "air_density_kg_m3",
    "wind_speed_mph",
    "wind_direction_deg",
    "wind_direction_cardinal",
    "wind_gust_mph",
    "wind_out_mph",
    "wind_cross_mph",
    "wind_field_direction",
)


def weather_icon(condition: object) -> str:
    text = str(condition or "").lower()
    if "thunder" in text:
        return "storm"
    if "rain" in text or "drizzle" in text or "shower" in text:
        return "rain"
    if "snow" in text:
        return "snow"
    if "fog" in text:
        return "fog"
    if "clear" in text and "mostly" not in text:
        return "clear"
    if "mostly clear" in text or "partly cloudy" in text:
        return "partly-cloudy"
    if "overcast" in text or "cloud" in text:
        return "cloudy"
    return "unknown"


def field_wind_arrow(field_direction: object) -> str:
    return {
        "Out to CF": "\u2191",
        "In from CF": "\u2193",
        "L to R": "\u2192",
        "R to L": "\u2190",
    }.get(str(field_direction), "\u00b7")


def safe_float(value: Any) -> float | None:
    try:
        if value is None or pd.isna(value):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def unavailable_weather(status: str, detail: object | None = None) -> dict[str, object]:
    result: dict[str, object] = {column: None for column in WEATHER_VALUE_COLUMNS}
    result.update(
        {
            "weather_status": status,
            "weather_condition": "Unavailable",
            "weather_icon": "unknown",
            "weather_display": "N/A",
            "weather_tooltip": "Forecast unavailable.",
            "weather_summary": "Forecast unavailable",
            "weather_edge": "Neutral",
            "wind_arrow": "\u00b7",
            "wind_display": "\u00b7",
            "wind_tooltip": "Wind forecast unavailable.",
            "hitter_weather_adjustment": 0.0,
            "pitcher_weather_adjustment": 0.0,
        }
    )
    if detail:
        result["weather_error"] = str(detail)
    return result


def parse_utc_datetime(value: object) -> datetime | None:
    if isinstance(value, datetime):
        result = value
    else:
        text = str(value or "").strip()
        if not text:
            return None
        result = datetime.fromisoformat(text.replace("Z", "+00:00"))

    if result.tzinfo is None:
        return result.replace(tzinfo=UTC)
    return result.astimezone(UTC)


def cardinal_direction(degrees: object) -> str | None:
    value = safe_float(degrees)
    if value is None:
        return None
    directions = (
        "N",
        "NNE",
        "NE",
        "ENE",
        "E",
        "ESE",
        "SE",
        "SSE",
        "S",
        "SSW",
        "SW",
        "WSW",
        "W",
        "WNW",
        "NW",
        "NNW",
    )
    return directions[int((value + 11.25) // 22.5) % 16]


def project_wind_to_field(
    wind_speed_mph: object,
    wind_from_degrees: object,
    field_azimuth: object,
) -> tuple[float | None, float | None, str]:
    speed = safe_float(wind_speed_mph)
    wind_from = safe_float(wind_from_degrees)
    azimuth = safe_float(field_azimuth)
    if speed is None or wind_from is None or azimuth is None:
        return None, None, "Direction unavailable"

    wind_to = (wind_from + 180.0) % 360.0
    difference = math.radians((wind_to - azimuth + 180.0) % 360.0 - 180.0)
    out_component = speed * math.cos(difference)
    cross_component = speed * math.sin(difference)
    if abs(out_component) >= max(2.0, abs(cross_component) * 0.75):
        label = "Out to CF" if out_component > 0 else "In from CF"
    else:
        label = "L to R" if cross_component > 0 else "R to L"
    return out_component, cross_component, label


def calculate_air_density(
    temp_f: object, humidity_pct: object, pressure_hpa: object
) -> float | None:
    temperature_f = safe_float(temp_f)
    humidity = safe_float(humidity_pct)
    pressure = safe_float(pressure_hpa)
    if temperature_f is None or humidity is None or pressure is None:
        return None

    temperature_c = (temperature_f - 32.0) * 5.0 / 9.0
    temperature_k = temperature_c + 273.15
    saturation_hpa = 6.112 * math.exp((17.67 * temperature_c) / (temperature_c + 243.5))
    vapor_hpa = max(0.0, min(pressure, humidity / 100.0 * saturation_hpa))
    dry_hpa = pressure - vapor_hpa
    return (dry_hpa * 100.0) / (287.05 * temperature_k) + (vapor_hpa * 100.0) / (
        461.495 * temperature_k
    )


def roof_allows_weather(roof_type: object) -> bool:
    return str(roof_type or "").strip().lower() == "open"


def calculate_weather_adjustments(
    out_component_mph: object,
    air_density: object,
    roof_type: object,
) -> tuple[float, float]:
    if not roof_allows_weather(roof_type):
        return 0.0, 0.0
    wind_out = safe_float(out_component_mph) or 0.0
    density = safe_float(air_density)
    density_adjustment = 0.0
    if density is not None:
        density_adjustment = max(-2.5, min(3.0, (1.20 - density) * 20.0))
    wind_adjustment = max(-4.5, min(4.5, wind_out * 0.35))
    hitter_adjustment = max(-6.0, min(6.0, wind_adjustment + density_adjustment))
    pitcher_adjustment = max(-1.5, min(1.5, -hitter_adjustment * 0.20))
    return round(hitter_adjustment, 2), round(pitcher_adjustment, 2)


def weather_edge_label(hitter_adjustment: object, roof_type: object) -> str:
    if not roof_allows_weather(roof_type):
        if str(roof_type or "").strip().lower() == "retractable":
            return "Roof TBD - neutral"
        return "Indoor - neutral"
    adjustment = safe_float(hitter_adjustment) or 0.0
    if adjustment >= 3.0:
        return "Strong hitter boost"
    if adjustment >= 1.0:
        return "Hitter boost"
    if adjustment <= -3.0:
        return "Strong pitcher boost"
    if adjustment <= -1.0:
        return "Pitcher boost"
    return "Neutral"


def pressure_at_elevation(sea_level_hpa: object, elevation_ft: object) -> float | None:
    pressure = safe_float(sea_level_hpa)
    elevation = safe_float(elevation_ft)
    if pressure is None:
        return None
    if elevation is None:
        return pressure
    elevation_m = max(-430.0, elevation * 0.3048)
    pressure_ratio = max(0.1, 1.0 - 2.25577e-5 * elevation_m)
    return float(pressure * pressure_ratio**5.25588)
