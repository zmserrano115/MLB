# src/mlb_schedule.py

import requests
import pandas as pd
from functools import lru_cache
from pathlib import Path

from src.api_client import get_json


SCHEDULE_URL = "https://statsapi.mlb.com/api/v1/schedule"
PEOPLE_URL = "https://statsapi.mlb.com/api/v1/people"
SCHEDULE_CACHE_DIR = Path(__file__).resolve().parents[1] / "data" / "precomputed"


def schedule_cache_path(game_date):
    safe_date = str(game_date).replace("/", "-")
    return SCHEDULE_CACHE_DIR / f"schedule-{safe_date}.json"


def read_cached_schedule(game_date):
    cache_path = schedule_cache_path(game_date)
    if not cache_path.exists():
        return pd.DataFrame()

    try:
        cached = pd.read_json(cache_path, orient="records")
    except (OSError, ValueError):
        return pd.DataFrame()

    cached.attrs["schedule_source"] = "saved"
    return cached


def write_cached_schedule(game_date, schedule):
    cache_path = schedule_cache_path(game_date)
    temp_path = cache_path.with_suffix(".tmp")
    try:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        schedule.to_json(temp_path, orient="records")
        temp_path.replace(cache_path)
    except OSError:
        temp_path.unlink(missing_ok=True)


@lru_cache(maxsize=256)
def get_pitcher_hand(player_id):
    if player_id is None:
        return None

    return get_pitcher_hands([player_id]).get(int(player_id))


def get_pitcher_hands(player_ids):
    player_ids = sorted(
        {
            int(player_id)
            for player_id in player_ids
            if player_id is not None
        }
    )
    if not player_ids:
        return {}

    try:
        data = get_json(
            PEOPLE_URL,
            params={"personIds": ",".join(str(player_id) for player_id in player_ids)},
            provider="MLB StatsAPI",
            timeout=20,
        )
        return {
            int(person["id"]): person.get("pitchHand", {}).get("code")
            for person in data.get("people", [])
            if person.get("id") is not None
        }
    except Exception:
        return {}


def get_daily_schedule(game_date):
    params = {
        "sportId": 1,
        "date": game_date,
        "hydrate": "probablePitcher(note),team,venue(location,fieldInfo),linescore",
    }

    try:
        data = get_json(
            SCHEDULE_URL,
            params=params,
            provider="MLB StatsAPI",
            timeout=20,
        )
    except requests.RequestException:
        cached = read_cached_schedule(game_date)
        if not cached.empty:
            return cached
        raise

    rows = []

    for day in data.get("dates", []):
        for game in day.get("games", []):
            away_team_data = game["teams"]["away"]["team"]
            home_team_data = game["teams"]["home"]["team"]

            away_team = away_team_data["name"]
            home_team = home_team_data["name"]

            away_team_id = away_team_data["id"]
            home_team_id = home_team_data["id"]
            away_team_abbr = away_team_data.get("abbreviation")
            home_team_abbr = home_team_data.get("abbreviation")

            away_pitcher = game["teams"]["away"].get("probablePitcher", {})
            home_pitcher = game["teams"]["home"].get("probablePitcher", {})

            away_pitcher_id = away_pitcher.get("id")
            home_pitcher_id = home_pitcher.get("id")
            venue = game.get("venue", {})
            location = venue.get("location", {})
            coordinates = location.get("defaultCoordinates", {})
            field_info = venue.get("fieldInfo", {})
            status = game.get("status", {})
            linescore = game.get("linescore", {})
            offense = linescore.get("offense") or {}
            field_dimensions = {
                "left_line": field_info.get("leftLine"),
                "left": field_info.get("left"),
                "left_center": field_info.get("leftCenter"),
                "center": field_info.get("center"),
                "right_center": field_info.get("rightCenter"),
                "right": field_info.get("right"),
                "right_line": field_info.get("rightLine"),
            }

            rows.append({
                "game_date": game_date,
                "game_time_utc": game.get("gameDate"),
                "game_pk": game.get("gamePk"),

                "away_team": away_team,
                "away_team_id": away_team_id,
                "away_team_abbr": away_team_abbr,

                "home_team": home_team,
                "home_team_id": home_team_id,
                "home_team_abbr": home_team_abbr,

                "away_score": game["teams"]["away"].get("score"),
                "home_score": game["teams"]["home"].get("score"),
                "game_status": status.get("detailedState"),
                "abstract_game_state": status.get("abstractGameState"),
                "current_inning": linescore.get("currentInning"),
                "current_inning_ordinal": linescore.get("currentInningOrdinal"),
                "inning_state": linescore.get("inningState"),
                "inning_half": linescore.get("inningHalf"),
                "balls": linescore.get("balls"),
                "strikes": linescore.get("strikes"),
                "outs": linescore.get("outs"),
                "runner_on_first": bool(offense.get("first")),
                "runner_on_second": bool(offense.get("second")),
                "runner_on_third": bool(offense.get("third")),

                "away_probable_pitcher": away_pitcher.get("fullName"),
                "away_probable_pitcher_id": away_pitcher_id,
                "away_pitcher_hand": None,

                "home_probable_pitcher": home_pitcher.get("fullName"),
                "home_probable_pitcher_id": home_pitcher_id,
                "home_pitcher_hand": None,

                "venue_id": venue.get("id"),
                "venue_name": venue.get("name"),
                "venue_city": location.get("city"),
                "venue_latitude": coordinates.get("latitude"),
                "venue_longitude": coordinates.get("longitude"),
                "field_azimuth": location.get("azimuthAngle"),
                "venue_elevation_ft": location.get("elevation"),
                "roof_type": field_info.get("roofType"),
                "field_dimensions": field_dimensions,
                "field_left_line": field_dimensions["left_line"],
                "field_left": field_dimensions["left"],
                "field_left_center": field_dimensions["left_center"],
                "field_center": field_dimensions["center"],
                "field_right_center": field_dimensions["right_center"],
                "field_right": field_dimensions["right"],
                "field_right_line": field_dimensions["right_line"],
            })

    pitcher_hands = get_pitcher_hands(
        [
            row.get("away_probable_pitcher_id")
            for row in rows
        ]
        + [
            row.get("home_probable_pitcher_id")
            for row in rows
        ]
    )
    for row in rows:
        row["away_pitcher_hand"] = pitcher_hands.get(
            row.get("away_probable_pitcher_id")
        )
        row["home_pitcher_hand"] = pitcher_hands.get(
            row.get("home_probable_pitcher_id")
        )

    schedule = pd.DataFrame(rows)
    schedule.attrs["schedule_source"] = "live"
    write_cached_schedule(game_date, schedule)
    return schedule
