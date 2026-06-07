# src/mlb_schedule.py

import requests
import pandas as pd
from functools import lru_cache


SCHEDULE_URL = "https://statsapi.mlb.com/api/v1/schedule"
PEOPLE_URL = "https://statsapi.mlb.com/api/v1/people"


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
        response = requests.get(
            PEOPLE_URL,
            params={"personIds": ",".join(str(player_id) for player_id in player_ids)},
            timeout=20,
        )
        response.raise_for_status()
        data = response.json()
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
        "hydrate": "probablePitcher(note),team"
    }

    response = requests.get(SCHEDULE_URL, params=params, timeout=20)
    response.raise_for_status()
    data = response.json()

    rows = []

    for day in data.get("dates", []):
        for game in day.get("games", []):
            away_team_data = game["teams"]["away"]["team"]
            home_team_data = game["teams"]["home"]["team"]

            away_team = away_team_data["name"]
            home_team = home_team_data["name"]

            away_team_id = away_team_data["id"]
            home_team_id = home_team_data["id"]

            away_pitcher = game["teams"]["away"].get("probablePitcher", {})
            home_pitcher = game["teams"]["home"].get("probablePitcher", {})

            away_pitcher_id = away_pitcher.get("id")
            home_pitcher_id = home_pitcher.get("id")

            rows.append({
                "game_date": game_date,
                "game_pk": game.get("gamePk"),

                "away_team": away_team,
                "away_team_id": away_team_id,

                "home_team": home_team,
                "home_team_id": home_team_id,

                "away_probable_pitcher": away_pitcher.get("fullName"),
                "away_probable_pitcher_id": away_pitcher_id,
                "away_pitcher_hand": None,

                "home_probable_pitcher": home_pitcher.get("fullName"),
                "home_probable_pitcher_id": home_pitcher_id,
                "home_pitcher_hand": None,
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

    return pd.DataFrame(rows)
