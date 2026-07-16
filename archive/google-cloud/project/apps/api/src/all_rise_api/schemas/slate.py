from __future__ import annotations

from datetime import date, datetime

from all_rise_api.schemas.common import StrictModel


class TeamBrief(StrictModel):
    name: str
    abbreviation: str | None = None
    score: int | None = None


class PitcherBrief(StrictModel):
    player_id: str
    name: str | None = None


class VenueBrief(StrictModel):
    name: str
    city: str | None = None
    roof_type: str | None = None


class GameData(StrictModel):
    game_id: str
    game_date: date
    season: int
    game_time_utc: datetime | None = None
    status: str | None = None
    away_team: TeamBrief
    home_team: TeamBrief
    away_probable_pitcher: PitcherBrief | None = None
    home_probable_pitcher: PitcherBrief | None = None
    venue: VenueBrief | None = None
    source_updated_at: datetime | None = None


class WeatherData(StrictModel):
    game_id: str
    game_date: date
    game_time_utc: datetime | None = None
    status: str | None = None
    away_team: TeamBrief
    home_team: TeamBrief
    venue: VenueBrief | None = None
    available: bool
    observed_at: datetime | None = None
    forecast_for: datetime | None = None
    source: str | None = None
    condition: str | None = None
    temperature_f: float | None = None
    feels_like_f: float | None = None
    humidity_percent: float | None = None
    wind_speed_mph: float | None = None
    wind_direction_degrees: float | None = None
    wind_out_mph: float | None = None
    precipitation_probability: float | None = None
    hitter_adjustment: float | None = None
    pitcher_adjustment: float | None = None
    edge_label: str | None = None
