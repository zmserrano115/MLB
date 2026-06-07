import argparse
from datetime import date, timedelta
import traceback

import requests

from src.database import (
    init_database,
    upsert_game,
    insert_plate_appearance,
    rebuild_batter_pitcher_stats,
    log_refresh,
)


MLB_SCHEDULE_URL = "https://statsapi.mlb.com/api/v1/schedule"
MLB_GAME_FEED_URL = "https://statsapi.mlb.com/api/v1.1/game/{game_pk}/feed/live"


def get_schedule_for_date(game_date):
    params = {
        "sportId": 1,
        "date": game_date,
        "hydrate": "probablePitcher",
    }

    response = requests.get(MLB_SCHEDULE_URL, params=params, timeout=30)
    response.raise_for_status()

    data = response.json()
    games = []

    for date_block in data.get("dates", []):
        for game in date_block.get("games", []):
            teams = game.get("teams", {})

            away = teams.get("away", {})
            home = teams.get("home", {})

            away_team = away.get("team", {})
            home_team = home.get("team", {})

            away_pitcher = away.get("probablePitcher", {})
            home_pitcher = home.get("probablePitcher", {})

            games.append(
                {
                    "game_pk": game.get("gamePk"),
                    "game_date": game_date,
                    "season": int(str(game_date)[:4]),
                    "away_team": away_team.get("name"),
                    "home_team": home_team.get("name"),
                    "away_team_id": away_team.get("id"),
                    "home_team_id": home_team.get("id"),
                    "away_probable_pitcher": away_pitcher.get("fullName"),
                    "away_probable_pitcher_id": away_pitcher.get("id"),
                    "home_probable_pitcher": home_pitcher.get("fullName"),
                    "home_probable_pitcher_id": home_pitcher.get("id"),
                    "game_status": game.get("status", {}).get("detailedState"),
                }
            )

    return games


def is_completed_game(game):
    status = str(game.get("game_status", "")).lower()

    completed_statuses = [
        "final",
        "game over",
        "completed early",
    ]

    return any(status_value in status for status_value in completed_statuses)


def get_game_feed(game_pk):
    url = MLB_GAME_FEED_URL.format(game_pk=game_pk)
    response = requests.get(url, timeout=45)
    response.raise_for_status()
    return response.json()


def get_team_name_from_feed(feed, team_type):
    try:
        return feed["gameData"]["teams"][team_type]["name"]
    except Exception:
        return None


def parse_plate_appearances(feed, game):
    all_plays = feed.get("liveData", {}).get("plays", {}).get("allPlays", [])

    away_team = game.get("away_team")
    home_team = game.get("home_team")

    plate_appearances = []

    for play_index, play in enumerate(all_plays):
        matchup = play.get("matchup", {})
        result = play.get("result", {})
        about = play.get("about", {})
        count = play.get("count", {})

        batter = matchup.get("batter", {})
        pitcher = matchup.get("pitcher", {})

        batter_id = batter.get("id")
        pitcher_id = pitcher.get("id")

        if batter_id is None or pitcher_id is None:
            continue

        event_type = result.get("eventType")
        event_name = result.get("event")
        description = result.get("description")

        inning = about.get("inning")
        half_inning = about.get("halfInning")

        if half_inning == "top":
            batting_team = away_team
            pitching_team = home_team
        else:
            batting_team = home_team
            pitching_team = away_team

        rbi = int(result.get("rbi", 0) or 0)

        is_bb = 1 if event_type in ["walk", "intent_walk"] else 0
        is_hbp = 1 if event_type == "hit_by_pitch" else 0
        is_so = 1 if event_type in ["strikeout", "strikeout_double_play"] else 0
        is_hr = 1 if event_type == "home_run" else 0

        hit_events = [
            "single",
            "double",
            "triple",
            "home_run",
        ]

        is_hit = 1 if event_type in hit_events else 0

        non_ab_events = [
            "walk",
            "intent_walk",
            "hit_by_pitch",
            "sac_bunt",
            "sac_fly",
            "catcher_interf",
            "sac_fly_double_play",
            "sac_bunt_double_play",
        ]

        is_ab = 0 if event_type in non_ab_events else 1

        pa_key = f"{game.get('game_pk')}_{play_index}_{batter_id}_{pitcher_id}"

        plate_appearances.append(
            {
                "pa_key": pa_key,
                "game_pk": game.get("game_pk"),
                "game_date": game.get("game_date"),
                "season": game.get("season"),
                "inning": inning,
                "half_inning": half_inning,
                "batter_id": batter_id,
                "batter_name": batter.get("fullName"),
                "pitcher_id": pitcher_id,
                "pitcher_name": pitcher.get("fullName"),
                "batting_team": batting_team,
                "pitching_team": pitching_team,
                "event_type": event_name or event_type,
                "description": description,
                "is_ab": is_ab,
                "is_hit": is_hit,
                "is_bb": is_bb,
                "is_hbp": is_hbp,
                "is_so": is_so,
                "is_hr": is_hr,
                "rbi": rbi,
            }
        )

    return plate_appearances


def refresh_completed_games(refresh_date):
    init_database()

    games = get_schedule_for_date(refresh_date)

    games_checked = 0
    plate_appearances_added = 0

    for game in games:
        upsert_game(game)
        games_checked += 1

        if not is_completed_game(game):
            continue

        feed = get_game_feed(game["game_pk"])
        plate_appearances = parse_plate_appearances(feed, game)

        for pa in plate_appearances:
            plate_appearances_added += insert_plate_appearance(pa)

    rebuild_batter_pitcher_stats()

    log_refresh(
        refresh_type="completed_games",
        refresh_date=refresh_date,
        games_checked=games_checked,
        plate_appearances_added=plate_appearances_added,
        status="success",
        message="Database refresh completed.",
    )

    print("Database refresh completed.")
    print(f"Refresh date: {refresh_date}")
    print(f"Games checked: {games_checked}")
    print(f"Plate appearances added: {plate_appearances_added}")


def main():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--date",
        default=None,
        help="Date to refresh in YYYY-MM-DD format. Defaults to yesterday.",
    )

    args = parser.parse_args()

    if args.date:
        refresh_date = args.date
    else:
        refresh_date = (date.today() - timedelta(days=1)).strftime("%Y-%m-%d")

    try:
        refresh_completed_games(refresh_date)
    except Exception as error:
        log_refresh(
            refresh_type="completed_games",
            refresh_date=refresh_date,
            games_checked=0,
            plate_appearances_added=0,
            status="error",
            message=str(error),
        )

        print("ERROR during database refresh")
        print(str(error))
        traceback.print_exc()
        raise


if __name__ == "__main__":
    main()