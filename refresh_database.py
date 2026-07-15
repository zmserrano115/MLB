import argparse
from collections import defaultdict
from datetime import date, timedelta
import traceback

from src.api_client import get_json
from src.database import (
    ensure_database,
    is_game_processed,
    save_completed_game,
    rebuild_all_summary_stats,
    log_refresh,
    print_database_counts,
)


MLB_SCHEDULE_URL = "https://statsapi.mlb.com/api/v1/schedule"
MLB_GAME_FEED_URL = "https://statsapi.mlb.com/api/v1.1/game/{game_pk}/feed/live"


PA_EVENT_TYPES = {
    "single",
    "double",
    "triple",
    "home_run",
    "walk",
    "intent_walk",
    "hit_by_pitch",
    "strikeout",
    "strikeout_double_play",
    "field_out",
    "force_out",
    "grounded_into_double_play",
    "double_play",
    "triple_play",
    "fielders_choice",
    "fielders_choice_out",
    "field_error",
    "sac_fly",
    "sac_bunt",
    "sac_fly_double_play",
    "sac_bunt_double_play",
    "catcher_interf",
    "other_out",
}

NON_AB_EVENT_TYPES = {
    "walk",
    "intent_walk",
    "hit_by_pitch",
    "sac_fly",
    "sac_bunt",
    "sac_fly_double_play",
    "sac_bunt_double_play",
    "catcher_interf",
}

HIT_EVENT_TYPES = {
    "single",
    "double",
    "triple",
    "home_run",
}


def safe_int(value, default=0):
    try:
        if value is None or value == "":
            return default
        return int(value)
    except Exception:
        return default


def safe_float(value, default=None):
    try:
        if value is None or value == "":
            return default
        return float(value)
    except Exception:
        return default


def ip_to_outs(ip_value):
    if ip_value is None:
        return 0

    text = str(ip_value).strip()

    if text == "":
        return 0

    if "." not in text:
        return safe_int(text) * 3

    innings, outs = text.split(".", 1)

    return safe_int(innings) * 3 + safe_int(outs)


def outs_to_baseball_ip(outs):
    if outs is None:
        return 0.0

    outs = int(outs)
    return (outs // 3) + (outs % 3) / 10.0


def get_schedule_for_date(game_date, game_type="R"):
    params = {
        "sportId": 1,
        "date": game_date,
        "hydrate": "probablePitcher",
        "gameType": game_type,
    }

    data = get_json(
        MLB_SCHEDULE_URL,
        params=params,
        provider="MLB StatsAPI",
        timeout=30,
    )
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
    return get_json(
        url,
        provider="MLB StatsAPI",
        timeout=45,
    )


def get_total_bases(event_type):
    if event_type == "single":
        return 1

    if event_type == "double":
        return 2

    if event_type == "triple":
        return 3

    if event_type == "home_run":
        return 4

    return 0


def pitch_type_from_event(event):
    details = event.get("details", {}) or {}
    pitch_type = details.get("type", {}) or {}
    pitch_code = pitch_type.get("code")
    if not pitch_code:
        return None, None
    if event.get("isPitch") is False and not event.get("pitchData"):
        return None, None
    return str(pitch_code).strip(), pitch_type.get("description") or pitch_code


def pitch_type_from_play(play):
    for event in reversed(play.get("playEvents", []) or []):
        pitch_code, pitch_name = pitch_type_from_event(event)
        if pitch_code:
            return pitch_code, pitch_name
    return None, None


def pitcher_hand_from_matchup(matchup):
    pitch_hand = (matchup or {}).get("pitchHand", {}) or {}
    code = str(pitch_hand.get("code") or "").strip().upper()
    if code in {"L", "R"}:
        return code
    description = str(pitch_hand.get("description") or "").strip().lower()
    if description.startswith("left"):
        return "L"
    if description.startswith("right"):
        return "R"
    return None


def parse_game_to_batter_pitch_type_logs(feed, game):
    all_plays = feed.get("liveData", {}).get("plays", {}).get("allPlays", [])
    away_team = game.get("away_team")
    home_team = game.get("home_team")

    grouped_logs = defaultdict(
        lambda: {
            "PA": 0,
            "AB": 0,
            "H": 0,
            "singles": 0,
            "doubles": 0,
            "triples": 0,
            "BB": 0,
            "HBP": 0,
            "SO": 0,
            "HR": 0,
            "SF": 0,
            "TB": 0,
        }
    )
    pitch_types = {}

    for play in all_plays:
        matchup = play.get("matchup", {}) or {}
        result = play.get("result", {}) or {}
        about = play.get("about", {}) or {}
        batter = matchup.get("batter", {}) or {}
        batter_id = batter.get("id")
        if batter_id is None:
            continue

        event_type = result.get("eventType")
        if event_type not in PA_EVENT_TYPES:
            continue

        pitch_code, pitch_name = pitch_type_from_play(play)
        pitcher_hand = pitcher_hand_from_matchup(matchup)
        if not pitch_code or not pitcher_hand:
            continue
        pitch_types[pitch_code] = pitch_name

        half_inning = about.get("halfInning")
        batting_team = away_team if half_inning == "top" else home_team
        key = (
            int(game.get("game_pk")),
            int(batter_id),
            batting_team,
            pitcher_hand,
            pitch_code,
        )
        log = grouped_logs[key]
        log["PA"] += 1

        if event_type not in NON_AB_EVENT_TYPES:
            log["AB"] += 1

        if event_type in HIT_EVENT_TYPES:
            log["H"] += 1
        if event_type == "single":
            log["singles"] += 1
        if event_type == "double":
            log["doubles"] += 1
        if event_type == "triple":
            log["triples"] += 1
        if event_type == "home_run":
            log["HR"] += 1
        if event_type in ["walk", "intent_walk"]:
            log["BB"] += 1
        if event_type == "hit_by_pitch":
            log["HBP"] += 1
        if event_type in ["strikeout", "strikeout_double_play"]:
            log["SO"] += 1
        if event_type in ["sac_fly", "sac_fly_double_play"]:
            log["SF"] += 1
        log["TB"] += get_total_bases(event_type)

    game_logs = []
    for key, values in grouped_logs.items():
        game_pk, batter_id, batting_team, pitcher_hand, pitch_code = key
        game_logs.append(
            {
                "game_pk": game_pk,
                "game_date": game.get("game_date"),
                "season": game.get("season"),
                "batter_id": batter_id,
                "batting_team": batting_team,
                "pitcher_hand": pitcher_hand,
                "pitch_code": pitch_code,
                **values,
            }
        )

    return pitch_types, game_logs


def parse_game_to_pitcher_pitch_type_logs(feed, game):
    all_plays = feed.get("liveData", {}).get("plays", {}).get("allPlays", [])
    away_team = game.get("away_team")
    home_team = game.get("home_team")

    grouped_logs = defaultdict(
        lambda: {
            "pitch_count": 0,
            "total_speed": 0.0,
            "measured_pitches": 0,
        }
    )
    players = {}
    pitch_types = {}

    for play in all_plays:
        matchup = play.get("matchup", {}) or {}
        about = play.get("about", {}) or {}
        pitcher = matchup.get("pitcher", {}) or {}
        pitcher_id = pitcher.get("id")
        if pitcher_id is None:
            continue

        half_inning = about.get("halfInning")
        if half_inning == "top":
            pitching_team = home_team
            opponent = away_team
        else:
            pitching_team = away_team
            opponent = home_team

        for event in play.get("playEvents", []) or []:
            pitch_code, pitch_name = pitch_type_from_event(event)
            if not pitch_code:
                continue

            pitcher_id = int(pitcher_id)
            players[pitcher_id] = pitcher.get("fullName")
            pitch_types[pitch_code] = pitch_name

            key = (
                int(game.get("game_pk")),
                pitcher_id,
                pitching_team,
                opponent,
                pitch_code,
            )
            log = grouped_logs[key]
            log["pitch_count"] += 1

            pitch_data = event.get("pitchData", {}) or {}
            speed = safe_float(pitch_data.get("startSpeed"), default=None)
            if speed is not None:
                log["total_speed"] += speed
                log["measured_pitches"] += 1

    game_logs = []
    for key, values in grouped_logs.items():
        game_pk, pitcher_id, pitching_team, opponent, pitch_code = key
        game_logs.append(
            {
                "game_pk": game_pk,
                "game_date": game.get("game_date"),
                "season": game.get("season"),
                "pitcher_id": pitcher_id,
                "team": pitching_team,
                "opponent": opponent,
                "pitch_code": pitch_code,
                **values,
            }
        )

    return players, pitch_types, game_logs


def parse_game_to_batter_pitcher_logs(feed, game):
    all_plays = feed.get("liveData", {}).get("plays", {}).get("allPlays", [])

    away_team = game.get("away_team")
    home_team = game.get("home_team")

    grouped_logs = defaultdict(
        lambda: {
            "PA": 0,
            "AB": 0,
            "H": 0,
            "doubles": 0,
            "triples": 0,
            "BB": 0,
            "HBP": 0,
            "SO": 0,
            "HR": 0,
            "RBI": 0,
            "SF": 0,
            "TB": 0,
        }
    )

    players = {}
    plate_appearances_loaded = 0

    for play in all_plays:
        matchup = play.get("matchup", {})
        result = play.get("result", {})
        about = play.get("about", {})

        batter = matchup.get("batter", {})
        pitcher = matchup.get("pitcher", {})

        batter_id = batter.get("id")
        pitcher_id = pitcher.get("id")

        if batter_id is None or pitcher_id is None:
            continue

        event_type = result.get("eventType")

        if event_type not in PA_EVENT_TYPES:
            continue

        batter_name = batter.get("fullName")
        pitcher_name = pitcher.get("fullName")

        players[batter_id] = batter_name
        players[pitcher_id] = pitcher_name

        half_inning = about.get("halfInning")

        if half_inning == "top":
            batting_team = away_team
            pitching_team = home_team
        else:
            batting_team = home_team
            pitching_team = away_team

        key = (
            int(game.get("game_pk")),
            int(batter_id),
            int(pitcher_id),
            batting_team,
            pitching_team,
        )

        log = grouped_logs[key]

        log["PA"] += 1
        log["RBI"] += safe_int(result.get("rbi"), 0)

        if event_type not in NON_AB_EVENT_TYPES:
            log["AB"] += 1

        if event_type in HIT_EVENT_TYPES:
            log["H"] += 1

        if event_type == "double":
            log["doubles"] += 1

        if event_type == "triple":
            log["triples"] += 1

        if event_type in ["walk", "intent_walk"]:
            log["BB"] += 1

        if event_type == "hit_by_pitch":
            log["HBP"] += 1

        if event_type in ["strikeout", "strikeout_double_play"]:
            log["SO"] += 1

        if event_type == "home_run":
            log["HR"] += 1

        if event_type in ["sac_fly", "sac_fly_double_play"]:
            log["SF"] += 1

        log["TB"] += get_total_bases(event_type)

        plate_appearances_loaded += 1

    game_logs = []

    for key, values in grouped_logs.items():
        game_pk, batter_id, pitcher_id, batting_team, pitching_team = key

        game_logs.append(
            {
                "game_pk": game_pk,
                "game_date": game.get("game_date"),
                "season": game.get("season"),
                "batter_id": batter_id,
                "pitcher_id": pitcher_id,
                "batting_team": batting_team,
                "pitching_team": pitching_team,
                **values,
            }
        )

    return players, game_logs, plate_appearances_loaded


def parse_pitcher_game_logs(feed, game):
    boxscore = feed.get("liveData", {}).get("boxscore", {}).get("teams", {})

    pitcher_logs = []
    players = {}

    for side in ["away", "home"]:
        team_box = boxscore.get(side, {})
        team_name = game.get("away_team") if side == "away" else game.get("home_team")
        opponent_name = game.get("home_team") if side == "away" else game.get("away_team")

        pitcher_ids = team_box.get("pitchers", []) or []
        player_dict = team_box.get("players", {}) or {}

        starter_id = pitcher_ids[0] if pitcher_ids else None

        for pitcher_id in pitcher_ids:
            player = player_dict.get(f"ID{pitcher_id}", {})

            if not player:
                continue

            person = player.get("person", {})
            pitcher_name = person.get("fullName")

            stats = player.get("stats", {}).get("pitching", {}) or {}

            if not stats:
                continue

            ip_outs = ip_to_outs(stats.get("inningsPitched"))

            players[pitcher_id] = pitcher_name

            pitcher_logs.append(
                {
                    "game_pk": game.get("game_pk"),
                    "game_date": game.get("game_date"),
                    "season": game.get("season"),
                    "pitcher_id": int(pitcher_id),
                    "pitcher_name": pitcher_name,
                    "team": team_name,
                    "opponent": opponent_name,
                    "is_starter": 1 if pitcher_id == starter_id else 0,
                    "IP_outs": ip_outs,
                    "IP": outs_to_baseball_ip(ip_outs),
                    "pitch_count": safe_int(stats.get("numberOfPitches"), 0),
                    "BF": safe_int(stats.get("battersFaced"), 0),
                    "H": safe_int(stats.get("hits"), 0),
                    "BB": safe_int(stats.get("baseOnBalls"), 0),
                    "HBP": safe_int(stats.get("hitBatsmen"), 0),
                    "SO": safe_int(stats.get("strikeOuts"), 0),
                    "HR": safe_int(stats.get("homeRuns"), 0),
                    "R": safe_int(stats.get("runs"), 0),
                    "ER": safe_int(stats.get("earnedRuns"), 0),
                }
            )

    return players, pitcher_logs


def process_completed_game(game, reprocess_existing=False, rebuild_after=False):
    game_pk = game.get("game_pk")

    if game_pk is None:
        return {
            "processed": False,
            "plate_appearances_loaded": 0,
            "pitcher_logs_loaded": 0,
            "message": "Missing gamePk.",
        }

    if not is_completed_game(game):
        return {
            "processed": False,
            "plate_appearances_loaded": 0,
            "pitcher_logs_loaded": 0,
            "message": "Game is not final.",
        }

    if is_game_processed(game_pk) and not reprocess_existing:
        return {
            "processed": False,
            "plate_appearances_loaded": 0,
            "pitcher_logs_loaded": 0,
            "message": "Game already processed.",
        }

    feed = get_game_feed(game_pk)

    bvp_players, bvp_game_logs, plate_appearances_loaded = parse_game_to_batter_pitcher_logs(feed, game)
    pitch_types, batter_pitch_type_logs = parse_game_to_batter_pitch_type_logs(feed, game)
    pitch_mix_players, pitcher_pitch_types, pitcher_pitch_type_logs = parse_game_to_pitcher_pitch_type_logs(feed, game)
    pitcher_players, pitcher_logs = parse_pitcher_game_logs(feed, game)

    all_players = {}
    all_players.update(bvp_players)
    all_players.update(pitch_mix_players)
    all_players.update(pitcher_players)
    pitch_types.update(pitcher_pitch_types)

    save_completed_game(
        game=game,
        players=all_players,
        batter_pitcher_logs=bvp_game_logs,
        batter_pitch_type_logs=batter_pitch_type_logs,
        pitcher_pitch_type_logs=pitcher_pitch_type_logs,
        pitch_types=pitch_types,
        pitcher_logs=pitcher_logs,
        plate_appearances_loaded=plate_appearances_loaded,
        reprocess_existing=reprocess_existing,
    )

    if rebuild_after:
        rebuild_all_summary_stats()

    return {
        "processed": True,
        "plate_appearances_loaded": plate_appearances_loaded,
        "pitcher_logs_loaded": len(pitcher_logs),
        "message": "Game processed.",
    }


def refresh_completed_games(
    refresh_date,
    game_type="R",
    reprocess_existing=False,
    rebuild_after=True,
    write_refresh_log=True,
):
    ensure_database()

    games = get_schedule_for_date(refresh_date, game_type=game_type)

    games_checked = 0
    games_processed = 0
    plate_appearances_loaded = 0
    pitcher_logs_loaded = 0
    errors = 0

    print("========================================")
    print("Starting aggregate MLB database refresh")
    print(f"Refresh date: {refresh_date}")
    print(f"Game type: {game_type}")
    print("========================================")

    for game in games:
        games_checked += 1

        try:
            result = process_completed_game(
                game,
                reprocess_existing=reprocess_existing,
                rebuild_after=False,
            )

            matchup = f"{game.get('away_team')} @ {game.get('home_team')}"

            if result["processed"]:
                games_processed += 1
                plate_appearances_loaded += result["plate_appearances_loaded"]
                pitcher_logs_loaded += result["pitcher_logs_loaded"]

                print(
                    f"Processed: {matchup} | "
                    f"PA loaded: {result['plate_appearances_loaded']} | "
                    f"Pitcher logs: {result['pitcher_logs_loaded']}"
                )
            else:
                print(f"Skipped: {matchup} | {result['message']}")

        except Exception as error:
            errors += 1
            print(f"ERROR processing game {game.get('game_pk')}: {error}")
            traceback.print_exc()

    if rebuild_after:
        print("Rebuilding summary stats...")
        rebuild_all_summary_stats()

    status = "success" if errors == 0 else "completed_with_errors"

    message = (
        f"Games checked: {games_checked}. "
        f"Games processed: {games_processed}. "
        f"Plate appearances loaded: {plate_appearances_loaded}. "
        f"Pitcher logs loaded: {pitcher_logs_loaded}. "
        f"Errors: {errors}."
    )

    if write_refresh_log:
        log_refresh(
            refresh_type="daily_completed_games",
            refresh_date=refresh_date,
            games_checked=games_checked,
            games_processed=games_processed,
            plate_appearances_loaded=plate_appearances_loaded,
            pitcher_logs_loaded=pitcher_logs_loaded,
            status=status,
            message=message,
        )

    print("========================================")
    print("Refresh finished")
    print(message)
    print("========================================")

    if rebuild_after:
        print_database_counts()

    return {
        "games_checked": games_checked,
        "games_processed": games_processed,
        "plate_appearances_loaded": plate_appearances_loaded,
        "pitcher_logs_loaded": pitcher_logs_loaded,
        "errors": errors,
    }


def main():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--date",
        default=None,
        help="Date to refresh in YYYY-MM-DD format. Defaults to yesterday.",
    )

    parser.add_argument(
        "--game-type",
        default="R",
        help="MLB game type. R = regular season.",
    )

    parser.add_argument(
        "--reprocess-existing",
        action="store_true",
        help="Reprocess games even if they were already loaded.",
    )

    args = parser.parse_args()

    if args.date:
        refresh_date = args.date
    else:
        refresh_date = (date.today() - timedelta(days=1)).strftime("%Y-%m-%d")

    try:
        refresh_completed_games(
            refresh_date=refresh_date,
            game_type=args.game_type,
            reprocess_existing=args.reprocess_existing,
        )
    except Exception as error:
        log_refresh(
            refresh_type="daily_completed_games",
            refresh_date=refresh_date,
            games_checked=0,
            games_processed=0,
            plate_appearances_loaded=0,
            pitcher_logs_loaded=0,
            status="error",
            message=str(error),
        )

        print("ERROR during aggregate database refresh")
        print(str(error))
        traceback.print_exc()
        raise


if __name__ == "__main__":
    main()
