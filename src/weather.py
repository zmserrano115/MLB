from datetime import datetime, timezone
import math
import time

import pandas as pd
import requests


FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
FORECAST_HEADERS = {"User-Agent": "AllRiseAnalytics/1.0"}
FORECAST_BATCH_SIZE = 20
HOURLY_FIELDS = (
    "temperature_2m",
    "relative_humidity_2m",
    "precipitation_probability",
    "surface_pressure",
    "wind_speed_10m",
    "wind_direction_10m",
    "wind_gusts_10m",
    "weather_code",
)

WEATHER_CODES = {
    0: "Clear",
    1: "Mostly clear",
    2: "Partly cloudy",
    3: "Overcast",
    45: "Fog",
    48: "Rime fog",
    51: "Light drizzle",
    53: "Drizzle",
    55: "Heavy drizzle",
    61: "Light rain",
    63: "Rain",
    65: "Heavy rain",
    71: "Light snow",
    73: "Snow",
    75: "Heavy snow",
    80: "Rain showers",
    81: "Rain showers",
    82: "Heavy showers",
    95: "Thunderstorms",
    96: "Thunderstorms",
    99: "Thunderstorms",
}

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
WEATHER_OUTPUT_COLUMNS = WEATHER_VALUE_COLUMNS + (
    "weather_status",
    "weather_condition",
    "weather_icon",
    "weather_display",
    "weather_tooltip",
    "weather_summary",
    "weather_edge",
    "wind_arrow",
    "wind_display",
    "wind_tooltip",
    "hitter_weather_adjustment",
    "pitcher_weather_adjustment",
)


def weather_icon(condition):
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


def field_wind_arrow(field_direction):
    return {
        "Out to CF": "↑",
        "In from CF": "↓",
        "L to R": "→",
        "R to L": "←",
    }.get(field_direction, "·")


def safe_float(value):
    try:
        if value is None or pd.isna(value):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def unavailable_weather(status, detail=None):
    result = {column: None for column in WEATHER_VALUE_COLUMNS}
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


def parse_utc_datetime(value):
    if isinstance(value, datetime):
        result = value
    else:
        text = str(value or "").strip()
        if not text:
            return None
        result = datetime.fromisoformat(text.replace("Z", "+00:00"))

    if result.tzinfo is None:
        return result.replace(tzinfo=timezone.utc)
    return result.astimezone(timezone.utc)


def cardinal_direction(degrees):
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


def project_wind_to_field(wind_speed_mph, wind_from_degrees, field_azimuth):
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


def calculate_air_density(temp_f, humidity_pct, pressure_hpa):
    temperature_f = safe_float(temp_f)
    humidity = safe_float(humidity_pct)
    pressure = safe_float(pressure_hpa)
    if temperature_f is None or humidity is None or pressure is None:
        return None

    temperature_c = (temperature_f - 32.0) * 5.0 / 9.0
    temperature_k = temperature_c + 273.15
    saturation_hpa = 6.112 * math.exp(
        (17.67 * temperature_c) / (temperature_c + 243.5)
    )
    vapor_hpa = max(0.0, min(pressure, humidity / 100.0 * saturation_hpa))
    dry_hpa = pressure - vapor_hpa
    return (
        (dry_hpa * 100.0) / (287.05 * temperature_k)
        + (vapor_hpa * 100.0) / (461.495 * temperature_k)
    )


def roof_allows_weather(roof_type):
    return str(roof_type or "").strip().lower() == "open"


def calculate_weather_adjustments(
    out_component_mph,
    air_density,
    roof_type,
):
    if not roof_allows_weather(roof_type):
        return 0.0, 0.0

    wind_out = safe_float(out_component_mph) or 0.0
    density = safe_float(air_density)
    density_adjustment = 0.0
    if density is not None:
        density_adjustment = max(-2.5, min(3.0, (1.20 - density) * 20.0))

    wind_adjustment = max(-4.5, min(4.5, wind_out * 0.35))
    hitter_adjustment = max(
        -6.0,
        min(6.0, wind_adjustment + density_adjustment),
    )

    # Weather changes run environment much more than strikeout skill.
    pitcher_adjustment = max(-1.5, min(1.5, -hitter_adjustment * 0.20))
    return round(hitter_adjustment, 2), round(pitcher_adjustment, 2)


def weather_edge_label(hitter_adjustment, roof_type):
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


def validate_forecast_payload(payload):
    payloads = payload if isinstance(payload, list) else [payload]
    if not payloads:
        raise ValueError("Weather provider returned an empty response")

    for forecast in payloads:
        if not isinstance(forecast, dict):
            raise ValueError("Weather provider returned invalid forecast data")
        if forecast.get("error"):
            raise ValueError(forecast.get("reason") or "Weather provider error")

        hourly = forecast.get("hourly")
        times = hourly.get("time") if isinstance(hourly, dict) else None
        if not isinstance(times, list) or not times:
            raise ValueError("Weather provider returned no hourly forecast")

        for field in HOURLY_FIELDS:
            values = hourly.get(field)
            if not isinstance(values, list) or len(values) != len(times):
                raise ValueError(
                    f"Weather provider returned incomplete {field} data"
                )


def request_forecast(params, attempts=3, timeout=20):
    last_error = None
    for attempt in range(attempts):
        try:
            response = requests.get(
                FORECAST_URL,
                params=params,
                headers=FORECAST_HEADERS,
                timeout=timeout,
            )
            response.raise_for_status()
            payload = response.json()
            validate_forecast_payload(payload)
            return payload
        except (requests.RequestException, ValueError) as error:
            last_error = error
            if attempt < attempts - 1:
                time.sleep(0.4 * (attempt + 1))
    raise last_error


def forecast_params(latitude, longitude, start_date, end_date):
    return {
        "latitude": latitude,
        "longitude": longitude,
        "hourly": ",".join(HOURLY_FIELDS),
        "temperature_unit": "fahrenheit",
        "wind_speed_unit": "mph",
        "timezone": "UTC",
        "start_date": start_date,
        "end_date": end_date,
    }


def fetch_hourly_forecast(latitude, longitude, forecast_date, attempts=3):
    return request_forecast(
        forecast_params(
            latitude,
            longitude,
            forecast_date,
            forecast_date,
        ),
        attempts=attempts,
    )


def fetch_hourly_forecasts(locations, start_date, end_date):
    forecasts = {}
    unique_locations = list(dict.fromkeys(locations))

    for offset in range(0, len(unique_locations), FORECAST_BATCH_SIZE):
        batch = unique_locations[offset : offset + FORECAST_BATCH_SIZE]
        latitudes = ",".join(str(latitude) for latitude, _ in batch)
        longitudes = ",".join(str(longitude) for _, longitude in batch)
        payload = request_forecast(
            forecast_params(
                latitudes,
                longitudes,
                start_date,
                end_date,
            ),
            attempts=2,
        )
        payloads = payload if isinstance(payload, list) else [payload]
        if len(payloads) != len(batch):
            raise ValueError("Weather provider returned an incomplete slate")
        forecasts.update(zip(batch, payloads))

    return forecasts


def nearest_hour_values(hourly, game_time):
    times = hourly.get("time", [])
    if not times:
        return None

    parsed_times = [
        parse_utc_datetime(f"{value}:00+00:00" if len(value) == 16 else value)
        for value in times
    ]
    index = min(
        range(len(parsed_times)),
        key=lambda item: abs((parsed_times[item] - game_time).total_seconds()),
    )

    values = {"forecast_time_utc": times[index]}
    for field in HOURLY_FIELDS:
        field_values = hourly.get(field, [])
        values[field] = field_values[index] if index < len(field_values) else None
    return values


def build_game_weather(game, forecast_data):
    game_time = parse_utc_datetime(game.get("game_time_utc"))
    if game_time is None:
        return unavailable_weather("Game time unavailable")

    values = nearest_hour_values(forecast_data.get("hourly", {}), game_time)
    if values is None:
        return unavailable_weather("Forecast unavailable")

    wind_speed = safe_float(values.get("wind_speed_10m"))
    wind_direction = safe_float(values.get("wind_direction_10m"))
    out_component, cross_component, field_direction = project_wind_to_field(
        wind_speed,
        wind_direction,
        game.get("field_azimuth"),
    )
    temp_f = safe_float(values.get("temperature_2m"))
    humidity = safe_float(values.get("relative_humidity_2m"))
    pressure = safe_float(values.get("surface_pressure"))
    air_density = calculate_air_density(temp_f, humidity, pressure)
    roof_type = game.get("roof_type")
    hitter_adjustment, pitcher_adjustment = calculate_weather_adjustments(
        out_component,
        air_density,
        roof_type,
    )
    weather_code = safe_float(values.get("weather_code"))
    condition = WEATHER_CODES.get(
        int(weather_code) if weather_code is not None else None,
        "Unknown",
    )
    cardinal = cardinal_direction(wind_direction)
    precipitation_probability = safe_float(
        values.get("precipitation_probability")
    )

    wind_text = "Wind unavailable"
    if wind_speed is not None:
        wind_text = f"{wind_speed:.0f} mph"
        if cardinal:
            wind_text += f" {cardinal}"
        if field_direction != "Direction unavailable":
            wind_text += f" ({field_direction})"

    temp_text = f"{temp_f:.0f} F" if temp_f is not None else "Temp unavailable"
    summary = f"{temp_text} | {wind_text} | {condition}"
    if precipitation_probability is not None:
        summary += f" | Rain {precipitation_probability:.0f}%"
    icon = weather_icon(condition)
    arrow = field_wind_arrow(field_direction)
    weather_display = condition
    if temp_f is not None:
        weather_display = f"{temp_f:.0f}°"
    wind_display = arrow
    if wind_speed is not None:
        wind_display += f" {wind_speed:.0f}"

    roof_text = str(roof_type or "Unknown roof")
    humidity_text = (
        f"{humidity:.0f}%" if humidity is not None else "unavailable"
    )
    rain_text = (
        f"{precipitation_probability:.0f}%"
        if precipitation_probability is not None
        else "unavailable"
    )
    weather_tooltip = (
        f"{condition}, {temp_text}. Humidity {humidity_text}; rain {rain_text}. "
        f"Roof: {roof_text}. Projection: "
        f"{weather_edge_label(hitter_adjustment, roof_type)} "
        f"({hitter_adjustment:+.2f} hitter adjustment)."
    )
    wind_tooltip = (
        f"{wind_text}. Arrow is relative to the field: "
        "up = out to center, down = in from center, left/right = crosswind. "
        "Wind blowing out generally helps carry; wind blowing in suppresses it."
    )

    return {
        "weather_status": "Forecast available",
        "forecast_time_utc": values.get("forecast_time_utc"),
        "temperature_f": temp_f,
        "humidity_pct": humidity,
        "precip_probability_pct": precipitation_probability,
        "surface_pressure_hpa": pressure,
        "air_density_kg_m3": air_density,
        "wind_speed_mph": wind_speed,
        "wind_direction_deg": wind_direction,
        "wind_direction_cardinal": cardinal,
        "wind_gust_mph": safe_float(values.get("wind_gusts_10m")),
        "wind_out_mph": out_component,
        "wind_cross_mph": cross_component,
        "wind_field_direction": field_direction,
        "weather_condition": condition,
        "weather_icon": icon,
        "weather_display": weather_display,
        "weather_tooltip": weather_tooltip,
        "weather_summary": summary,
        "weather_edge": weather_edge_label(hitter_adjustment, roof_type),
        "wind_arrow": arrow,
        "wind_display": wind_display,
        "wind_tooltip": wind_tooltip,
        "hitter_weather_adjustment": hitter_adjustment,
        "pitcher_weather_adjustment": pitcher_adjustment,
    }


def enrich_schedule_with_weather(schedule_df, forecast_loader=None):
    if schedule_df.empty:
        return schedule_df

    games = [game_row.to_dict() for _, game_row in schedule_df.iterrows()]
    rows = []

    if forecast_loader is not None:
        forecast_cache = {}
        for game in games:
            latitude = safe_float(game.get("venue_latitude"))
            longitude = safe_float(game.get("venue_longitude"))
            game_time = parse_utc_datetime(game.get("game_time_utc"))
            if latitude is None or longitude is None or game_time is None:
                game.update(unavailable_weather("Venue forecast unavailable"))
                rows.append(game)
                continue

            forecast_date = game_time.date().isoformat()
            cache_key = (round(latitude, 5), round(longitude, 5), forecast_date)
            try:
                if cache_key not in forecast_cache:
                    forecast_cache[cache_key] = forecast_loader(
                        latitude,
                        longitude,
                        forecast_date,
                    )
                game.update(build_game_weather(game, forecast_cache[cache_key]))
            except Exception as error:
                game.update(
                    unavailable_weather("Forecast unavailable", detail=error)
                )
            rows.append(game)
        return pd.DataFrame(rows)

    locations = []
    forecast_dates = []
    for game in games:
        latitude = safe_float(game.get("venue_latitude"))
        longitude = safe_float(game.get("venue_longitude"))
        game_time = parse_utc_datetime(game.get("game_time_utc"))
        if latitude is None or longitude is None or game_time is None:
            continue
        locations.append((round(latitude, 5), round(longitude, 5)))
        forecast_dates.append(game_time.date().isoformat())

    forecasts = {}
    forecast_errors = {}
    if locations:
        unique_locations = list(dict.fromkeys(locations))
        start_date = min(forecast_dates)
        end_date = max(forecast_dates)
        try:
            forecasts = fetch_hourly_forecasts(
                unique_locations,
                start_date,
                end_date,
            )
        except Exception as batch_error:
            status_code = getattr(
                getattr(batch_error, "response", None),
                "status_code",
                None,
            )
            allow_individual_fallback = (
                isinstance(batch_error, ValueError)
                or status_code == 400
            )
            if not allow_individual_fallback:
                forecast_errors = {
                    location: batch_error for location in unique_locations
                }
            else:
                for location in unique_locations:
                    try:
                        forecasts[location] = request_forecast(
                            forecast_params(
                                location[0],
                                location[1],
                                start_date,
                                end_date,
                            ),
                            attempts=1,
                            timeout=10,
                        )
                    except Exception as fallback_error:
                        forecast_errors[location] = fallback_error

    for game in games:
        latitude = safe_float(game.get("venue_latitude"))
        longitude = safe_float(game.get("venue_longitude"))
        game_time = parse_utc_datetime(game.get("game_time_utc"))
        if latitude is None or longitude is None or game_time is None:
            game.update(unavailable_weather("Venue forecast unavailable"))
            rows.append(game)
            continue

        location = (round(latitude, 5), round(longitude, 5))
        forecast = forecasts.get(location)
        if forecast is None:
            game.update(
                unavailable_weather(
                    "Forecast unavailable",
                    detail=forecast_errors.get(location),
                )
            )
        else:
            game.update(build_game_weather(game, forecast))
        rows.append(game)

    return pd.DataFrame(rows)


def preserve_previous_weather(current_df, previous_df):
    if (
        current_df is None
        or current_df.empty
        or previous_df is None
        or previous_df.empty
        or "game_pk" not in current_df.columns
        or "game_pk" not in previous_df.columns
    ):
        return current_df

    result = current_df.copy()
    previous_by_game = previous_df.drop_duplicates("game_pk").set_index("game_pk")
    for index, row in result.iterrows():
        if row.get("weather_status") == "Forecast available":
            continue

        game_pk = row.get("game_pk")
        if game_pk not in previous_by_game.index:
            continue

        previous = previous_by_game.loc[game_pk]
        if previous.get("weather_status") != "Forecast available":
            continue

        for column in WEATHER_OUTPUT_COLUMNS:
            if column in previous.index:
                result.at[index, column] = previous.get(column)
        result.at[index, "weather_source"] = "Last successful forecast"

    return result
