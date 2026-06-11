# src/stat_data.py

import pandas as pd
import requests

from src.database import (
    get_batter_vs_pitcher_game_logs_from_db,
    get_batter_vs_pitcher_stats_from_db,
    get_pitcher_vs_team_game_logs_from_db,
)

STATS_URL = "https://statsapi.mlb.com/api/v1/stats"
HAND_SPLIT_CACHE = {}


def make_numeric(df, columns):
    """
    Converts selected columns to numeric.
    """
    for col in columns:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    return df


def safe_number(value):
    """
    Converts values to clean Python numbers or None.
    """
    value = pd.to_numeric(value, errors="coerce")

    if pd.isna(value):
        return None

    return float(value)


def safe_int(value):
    """
    Converts values to clean Python ints or 0.
    """
    value = pd.to_numeric(value, errors="coerce")

    if pd.isna(value):
        return 0

    return int(value)


def safe_divide(numerator, denominator):
    """
    Safely divides two numbers.
    """
    numerator = safe_number(numerator)
    denominator = safe_number(denominator)

    if denominator in [0, None]:
        return None

    if numerator is None:
        return None

    return numerator / denominator

def is_missing(value):
    """
    Checks for None, NaN, or blank values.
    """
    if value is None:
        return True

    try:
        if pd.isna(value):
            return True
    except Exception:
        pass

    if str(value).strip() == "":
        return True

    return False


def get_mlb_stats(season, group):
    """
    Pulls season stats directly from MLB Stats API.

    group can be:
    - hitting
    - pitching
    """
    params = {
        "stats": "season",
        "group": group,
        "playerPool": "ALL",
        "season": season,
        "sportIds": 1,
        "limit": 5000
    }

    response = requests.get(STATS_URL, params=params, timeout=30)
    response.raise_for_status()

    data = response.json()
    splits = data.get("stats", [{}])[0].get("splits", [])

    rows = []

    for item in splits:
        player = item.get("player", {})
        team = item.get("team", {})
        stat = item.get("stat", {})

        row = {
            "player_id": player.get("id"),
            "Name": player.get("fullName"),
            "team_id": team.get("id"),
            "team_name": team.get("name"),
            "Team": team.get("abbreviation"),
        }

        row.update(stat)
        rows.append(row)

    return pd.DataFrame(rows)


def get_batter_stats(season, force_refresh=False):
    """
    Pulls batter season stats live from MLB StatsAPI.

    force_refresh is retained for compatibility with the Streamlit cache.
    """
    df = get_mlb_stats(season, "hitting")

    if df.empty:
        return pd.DataFrame()

    rename_cols = {
        "plateAppearances": "PA",
        "avg": "AVG",
        "obp": "OBP",
        "slg": "SLG",
        "ops": "OPS",
        "strikeOuts": "SO",
        "baseOnBalls": "BB"
    }

    df = df.rename(columns=rename_cols)

    keep_cols = [
        "player_id",
        "Name",
        "team_id",
        "team_name",
        "Team",
        "PA",
        "AVG",
        "OBP",
        "SLG",
        "OPS",
        "SO",
        "BB"
    ]

    available_cols = [col for col in keep_cols if col in df.columns]
    df = df[available_cols].copy()

    numeric_cols = [
        "player_id",
        "team_id",
        "PA",
        "AVG",
        "OBP",
        "SLG",
        "OPS",
        "SO",
        "BB"
    ]

    df = make_numeric(df, numeric_cols)

    df["K%"] = (df["SO"] / df["PA"]) * 100
    df["BB%"] = (df["BB"] / df["PA"]) * 100

    df = df.dropna(subset=["Name", "team_id"])

    return df


def get_pitcher_stats(season, force_refresh=False):
    """
    Pulls pitcher season stats from MLB Stats API.

    Keeps:
    - IP = season innings pitched
    - GS = games started
    - Pitches = season pitch count, if available
    """
    df = get_mlb_stats(season, "pitching")

    if df.empty:
        return pd.DataFrame()

    rename_cols = {
        "inningsPitched": "IP",
        "hits": "H",
        "era": "ERA",
        "whip": "WHIP",
        "strikeoutsPer9Inn": "K/9",
        "walksPer9Inn": "BB/9",
        "strikeOuts": "SO",
        "baseOnBalls": "BB",
        "battersFaced": "BF",
        "gamesStarted": "GS",
        "numberOfPitches": "Pitches"
    }

    df = df.rename(columns=rename_cols)

    if "GS" not in df.columns:
        df["GS"] = None

    if "Pitches" not in df.columns:
        df["Pitches"] = None

    keep_cols = [
        "player_id",
        "Name",
        "team_id",
        "team_name",
        "Team",
        "IP",
        "GS",
        "Pitches",
        "H",
        "ERA",
        "WHIP",
        "K/9",
        "BB/9",
        "SO",
        "BB",
        "BF"
    ]

    available_cols = [col for col in keep_cols if col in df.columns]
    df = df[available_cols].copy()

    numeric_cols = [
        "player_id",
        "team_id",
        "GS",
        "Pitches",
        "H",
        "ERA",
        "WHIP",
        "K/9",
        "BB/9",
        "SO",
        "BB",
        "BF"
    ]

    df = make_numeric(df, numeric_cols)

    df["K%"] = (df["SO"] / df["BF"]) * 100
    df["BB%"] = (df["BB"] / df["BF"]) * 100

    df["SwStr%"] = None

    df = df.dropna(subset=["Name", "team_id"])

    return df


def clean_stat_result(stat):
    """
    Converts MLB stat dictionary into clean matchup/split columns.
    """
    if not stat:
        return {
            "AB": 0,
            "PA": 0,
            "H": 0,
            "BB": 0,
            "SO": 0,
            "HR": 0,
            "RBI": 0,
            "AVG": None,
            "OBP": None,
            "SLG": None,
            "OPS": None,
            "K%": None,
            "BB%": None,
        }

    ab = safe_int(stat.get("atBats", 0))
    pa = safe_int(stat.get("plateAppearances", 0))
    h = safe_int(stat.get("hits", 0))
    bb = safe_int(stat.get("baseOnBalls", 0))
    so = safe_int(stat.get("strikeOuts", 0))
    hr = safe_int(stat.get("homeRuns", 0))
    rbi = safe_int(stat.get("rbi", 0))

    k_rate = safe_divide(so, pa)
    bb_rate = safe_divide(bb, pa)

    return {
        "AB": ab,
        "PA": pa,
        "H": h,
        "BB": bb,
        "SO": so,
        "HR": hr,
        "RBI": rbi,
        "AVG": safe_number(stat.get("avg")),
        "OBP": safe_number(stat.get("obp")),
        "SLG": safe_number(stat.get("slg")),
        "OPS": safe_number(stat.get("ops")),
        "K%": k_rate * 100 if k_rate is not None else None,
        "BB%": bb_rate * 100 if bb_rate is not None else None,
    }


def get_hitter_vs_pitcher_stats(batter_id, pitcher_id, season):
    """
    Returns career batter-vs-pitcher history from SQLite.

    The season argument remains in the public signature because the matchup
    builder already passes it, but direct BvP history is intentionally career
    history across the imported 2005-present database.
    """
    if is_missing(batter_id) or is_missing(pitcher_id):
        return get_batter_vs_pitcher_stats_from_db(None, None)

    try:
        batter_id = int(batter_id)
        pitcher_id = int(pitcher_id)
    except Exception:
        return get_batter_vs_pitcher_stats_from_db(None, None)

    return get_batter_vs_pitcher_stats_from_db(batter_id, pitcher_id)


def get_hitter_vs_hand_stats(batter_id, pitcher_hand, season):
    """
    Pulls hitter split against the opposing pitcher's throwing hand.

    R = hitter vs right-handed pitchers
    L = hitter vs left-handed pitchers
    """
    if batter_id is None or pitcher_hand not in ["R", "L"]:
        return clean_stat_result({})

    if pitcher_hand == "R":
        sit_code = "vr"
    else:
        sit_code = "vl"

    cache_key = (int(season), pitcher_hand)
    if cache_key not in HAND_SPLIT_CACHE:
        HAND_SPLIT_CACHE[cache_key] = {}

    params = {
        "stats": "statSplits",
        "group": "hitting",
        "sitCodes": sit_code,
        "sportIds": 1,
        "season": int(season),
        "playerPool": "ALL",
        "limit": 5000,
    }

    try:
        if not HAND_SPLIT_CACHE[cache_key]:
            response = requests.get(STATS_URL, params=params, timeout=30)
            response.raise_for_status()
            data = response.json()
            splits = data.get("stats", [{}])[0].get("splits", [])
            HAND_SPLIT_CACHE[cache_key] = {
                int(split["player"]["id"]): clean_stat_result(split.get("stat", {}))
                for split in splits
                if split.get("player", {}).get("id") is not None
            }
    except Exception:
        return clean_stat_result({})

    return HAND_SPLIT_CACHE[cache_key].get(
        int(batter_id),
        clean_stat_result({}),
    )


def get_batter_vs_pitcher_game_log(batter_id, pitcher_id, season=None):
    """
    Loads career game-log history for one batter vs one pitcher from SQLite.
    """
    if is_missing(batter_id) or is_missing(pitcher_id):
        return pd.DataFrame()

    try:
        batter_id = int(batter_id)
        pitcher_id = int(pitcher_id)
    except Exception:
        return pd.DataFrame()

    rows = get_batter_vs_pitcher_game_logs_from_db(batter_id, pitcher_id)
    return pd.DataFrame(rows)


def get_pitcher_vs_team_game_log(pitcher_id, opponent_team):
    """
    Loads career pitcher game logs against one opponent from SQLite.
    """
    if pitcher_id is None or opponent_team is None:
        return pd.DataFrame()

    try:
        pitcher_id = int(pitcher_id)
    except (TypeError, ValueError):
        return pd.DataFrame()

    rows = get_pitcher_vs_team_game_logs_from_db(pitcher_id, opponent_team)
    return pd.DataFrame(rows)
