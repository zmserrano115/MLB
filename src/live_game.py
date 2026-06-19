from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date

import pandas as pd
import requests


BOXSCORE_URL = "https://statsapi.mlb.com/api/v1/game/{game_pk}/boxscore"
PLAYER_STATS_URL = "https://statsapi.mlb.com/api/v1/people/{player_id}/stats"
PEOPLE_URL = "https://statsapi.mlb.com/api/v1/people"


def safe_int(value, default=0):
    value = pd.to_numeric(value, errors="coerce")
    if pd.isna(value):
        return default
    return int(value)


def player_headshot_url(player_id, width=80):
    if player_id is None:
        return ""

    player_id = pd.to_numeric(player_id, errors="coerce")
    if pd.isna(player_id):
        return ""

    return (
        "https://img.mlbstatic.com/mlb-photos/image/upload/"
        f"w_{int(width)},d_people:generic:headshot:silo:current.png,"
        f"q_auto:best,f_auto/v1/people/{int(player_id)}/headshot/67/current"
    )


def _player_record(players, player_id):
    return players.get(f"ID{int(player_id)}", {})


def _ordered_player_ids(team_data, list_name, stat_group):
    players = team_data.get("players", {})
    ordered_ids = team_data.get(list_name) or []
    if ordered_ids:
        return ordered_ids

    fallback = []
    for key, player in players.items():
        if not key.startswith("ID"):
            continue
        stats = player.get("stats", {}).get(stat_group, {})
        if stats:
            fallback.append(safe_int(key.replace("ID", ""), default=None))
    return [player_id for player_id in fallback if player_id is not None]


def _plate_appearances(stat):
    return sum(
        safe_int(stat.get(column))
        for column in (
            "atBats",
            "baseOnBalls",
            "hitByPitch",
            "sacFlies",
            "sacBunts",
        )
    )


def parse_game_boxscore(data):
    batting_rows = []
    pitching_rows = []

    for side in ("away", "home"):
        team_data = data.get("teams", {}).get(side, {})
        team = team_data.get("team", {})
        team_name = team.get("name")
        team_abbr = team.get("abbreviation") or team_name
        players = team_data.get("players", {})

        for player_id in _ordered_player_ids(team_data, "batters", "batting"):
            player = _player_record(players, player_id)
            person = player.get("person", {})
            stat = player.get("stats", {}).get("batting", {})
            season_stat = player.get("seasonStats", {}).get("batting", {})
            batting_rows.append(
                {
                    "player_id": person.get("id") or player_id,
                    "Headshot": player_headshot_url(person.get("id") or player_id),
                    "Player": person.get("fullName"),
                    "Team": team_abbr,
                    "team_name": team_name,
                    "Side": side.title(),
                    "Pos": player.get("position", {}).get("abbreviation"),
                    "PA": _plate_appearances(stat),
                    "AB": safe_int(stat.get("atBats")),
                    "R": safe_int(stat.get("runs")),
                    "H": safe_int(stat.get("hits")),
                    "RBI": safe_int(stat.get("rbi")),
                    "BB": safe_int(stat.get("baseOnBalls")),
                    "SO": safe_int(stat.get("strikeOuts")),
                    "HR": safe_int(stat.get("homeRuns")),
                    "SB": safe_int(stat.get("stolenBases")),
                    "AVG": season_stat.get("avg"),
                    "OPS": season_stat.get("ops"),
                }
            )

        for player_id in _ordered_player_ids(team_data, "pitchers", "pitching"):
            player = _player_record(players, player_id)
            person = player.get("person", {})
            stat = player.get("stats", {}).get("pitching", {})
            season_stat = player.get("seasonStats", {}).get("pitching", {})
            pitch_count = safe_int(stat.get("pitchesThrown"))
            strikes = safe_int(stat.get("strikes"))
            pitching_rows.append(
                {
                    "player_id": person.get("id") or player_id,
                    "Headshot": player_headshot_url(person.get("id") or player_id),
                    "Player": person.get("fullName"),
                    "Team": team_abbr,
                    "team_name": team_name,
                    "Side": side.title(),
                    "IP": stat.get("inningsPitched") or "0.0",
                    "H": safe_int(stat.get("hits")),
                    "R": safe_int(stat.get("runs")),
                    "ER": safe_int(stat.get("earnedRuns")),
                    "BB": safe_int(stat.get("baseOnBalls")),
                    "SO": safe_int(stat.get("strikeOuts")),
                    "HR": safe_int(stat.get("homeRuns")),
                    "PC-ST": f"{pitch_count}-{strikes}" if pitch_count else "",
                    "Pitch Count": pitch_count,
                    "ERA": season_stat.get("era"),
                    "WHIP": season_stat.get("whip"),
                }
            )

    return {
        "batting": pd.DataFrame(batting_rows),
        "pitching": pd.DataFrame(pitching_rows),
    }


def get_game_boxscore(game_pk):
    response = requests.get(BOXSCORE_URL.format(game_pk=int(game_pk)), timeout=20)
    response.raise_for_status()
    return parse_game_boxscore(response.json())


def parse_player_game_log(data, group):
    rows = []
    for split in data.get("stats", [{}])[0].get("splits", []):
        stat = split.get("stat", {})
        row = {
            "game_pk": split.get("game", {}).get("gamePk"),
            "game_date": split.get("date"),
            "opponent": split.get("opponent", {}).get("name"),
            "team": split.get("team", {}).get("abbreviation")
            or split.get("team", {}).get("name"),
            "home_away": "Home" if split.get("isHome") else "Away",
        }
        if group == "pitching":
            row.update(
                {
                    "IP": stat.get("inningsPitched"),
                    "Pitch Count": safe_int(stat.get("numberOfPitches")),
                    "BF": safe_int(stat.get("battersFaced")),
                    "SO": safe_int(stat.get("strikeOuts")),
                    "H": safe_int(stat.get("hits")),
                    "R": safe_int(stat.get("runs")),
                    "ER": safe_int(stat.get("earnedRuns")),
                    "BB": safe_int(stat.get("baseOnBalls")),
                    "HBP": safe_int(stat.get("hitBatsmen")),
                    "HR": safe_int(stat.get("homeRuns")),
                }
            )
        else:
            pa = safe_int(stat.get("plateAppearances"))
            ab = safe_int(stat.get("atBats"))
            hits = safe_int(stat.get("hits"))
            walks = safe_int(stat.get("baseOnBalls"))
            hbp = safe_int(stat.get("hitByPitch"))
            sac_flies = safe_int(stat.get("sacFlies"))
            total_bases = safe_int(stat.get("totalBases"))
            denominator = ab + walks + hbp + sac_flies
            obp = (hits + walks + hbp) / denominator if denominator else None
            slg = total_bases / ab if ab else None
            row.update(
                {
                    "PA": pa,
                    "AB": ab,
                    "H": hits,
                    "TB": total_bases,
                    "BB": walks,
                    "HBP": hbp,
                    "HR": safe_int(stat.get("homeRuns")),
                    "RBI": safe_int(stat.get("rbi")),
                    "R": safe_int(stat.get("runs")),
                    "SB": safe_int(stat.get("stolenBases")),
                    "SO": safe_int(stat.get("strikeOuts")),
                    "AVG": round(hits / ab, 3) if ab else None,
                    "OBP": round(obp, 3) if obp is not None else None,
                    "SLG": round(slg, 3) if slg is not None else None,
                    "OPS": (
                        round(obp + slg, 3)
                        if obp is not None and slg is not None
                        else None
                    ),
                    "K%": (
                        round((safe_int(stat.get("strikeOuts")) / pa) * 100, 2)
                        if pa
                        else None
                    ),
                    "BB%": round((walks / pa) * 100, 2) if pa else None,
                }
            )
        rows.append(row)

    return pd.DataFrame(rows)


def get_player_game_log(player_id, group, season):
    response = requests.get(
        PLAYER_STATS_URL.format(player_id=int(player_id)),
        params={
            "stats": "gameLog",
            "group": group,
            "season": int(season),
            "sportIds": 1,
        },
        timeout=20,
    )
    response.raise_for_status()
    return parse_player_game_log(response.json(), group)


def get_people_game_logs(player_ids, group, season):
    clean_ids = []
    for player_id in player_ids:
        player_id = pd.to_numeric(player_id, errors="coerce")
        if pd.notna(player_id):
            clean_ids.append(int(player_id))

    clean_ids = list(dict.fromkeys(clean_ids))
    if not clean_ids:
        return pd.DataFrame()

    def load_chunk(chunk):
        response = requests.get(
            PEOPLE_URL,
            params={
                "personIds": ",".join(str(player_id) for player_id in chunk),
                "hydrate": (
                    f"stats(group=[{group}],type=[gameLog],season={int(season)})"
                ),
                "sportIds": 1,
            },
            timeout=30,
        )
        response.raise_for_status()

        frames = []
        for person in response.json().get("people", []):
            frame = parse_player_game_log(
                {"stats": person.get("stats", [])},
                group,
            )
            if frame.empty:
                continue
            frame["player_id"] = person.get("id")
            frames.append(frame)
        return frames

    chunks = [
        clean_ids[offset : offset + 100]
        for offset in range(0, len(clean_ids), 100)
    ]
    frames = []
    with ThreadPoolExecutor(max_workers=min(8, len(chunks))) as executor:
        futures = [executor.submit(load_chunk, chunk) for chunk in chunks]
        for future in as_completed(futures):
            frames.extend(future.result())

    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def is_final_state(game_state, detailed_state=None):
    values = {str(game_state or "").lower(), str(detailed_state or "").lower()}
    return "final" in values or any("final" in value for value in values)


def count_historical_streak(game_log_df, stat_column, threshold, skip_date=None):
    if game_log_df is None or game_log_df.empty or stat_column not in game_log_df:
        return 0

    logs = game_log_df.copy()
    logs["parsed_date"] = pd.to_datetime(logs["game_date"], errors="coerce")
    logs = logs.dropna(subset=["parsed_date"])
    if skip_date is not None:
        skip_date = pd.to_datetime(skip_date).date()
        logs = logs[logs["parsed_date"].dt.date != skip_date]
    logs = logs.sort_values("parsed_date", ascending=False)

    streak = 0
    for _, row in logs.iterrows():
        value = pd.to_numeric(row.get(stat_column), errors="coerce")
        if pd.notna(value) and float(value) >= threshold:
            streak += 1
            continue
        break
    return streak


def calculate_live_streak(
    game_log_df,
    stat_column,
    threshold,
    current_value=None,
    current_game_state=None,
    detailed_state=None,
    selected_date=None,
    live_played=False,
):
    current_value = pd.to_numeric(current_value, errors="coerce")
    has_current_value = pd.notna(current_value)
    skip_date = selected_date if has_current_value or live_played else None
    base_streak = count_historical_streak(
        game_log_df,
        stat_column,
        threshold,
        skip_date=skip_date,
    )

    if has_current_value and float(current_value) >= threshold:
        return {
            "streak": base_streak + 1,
            "today_value": float(current_value),
            "status": "Live +1",
        }

    if live_played and is_final_state(current_game_state, detailed_state):
        return {
            "streak": 0,
            "today_value": float(current_value) if has_current_value else 0,
            "status": "Ended",
        }

    if live_played:
        return {
            "streak": base_streak,
            "today_value": float(current_value) if has_current_value else 0,
            "status": "In progress",
        }

    if isinstance(selected_date, date):
        status = "Pre-game"
    else:
        status = "Pending"
    return {
        "streak": base_streak,
        "today_value": float(current_value) if has_current_value else None,
        "status": status,
    }
