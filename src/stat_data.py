# src/stat_data.py

from pathlib import Path
from datetime import datetime, timedelta, date
import json

import pandas as pd
import requests

from pybaseball import statcast_batter, cache as pybaseball_cache


try:
    pybaseball_cache.enable()
except Exception:
    pass


CACHE_DIR = Path("data")
CACHE_DIR.mkdir(exist_ok=True)

STATS_URL = "https://statsapi.mlb.com/api/v1/stats"
PLAYER_STATS_URL = "https://statsapi.mlb.com/api/v1/people/{}/stats"

MATCHUP_CACHE_FILE = CACHE_DIR / "matchup_cache.json"


def cache_is_fresh(file_path, hours=12):
    """
    Checks if a cached CSV file is recent enough.
    """
    if not file_path.exists():
        return False

    modified_time = datetime.fromtimestamp(file_path.stat().st_mtime)
    return datetime.now() - modified_time < timedelta(hours=hours)


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


def clean_json_value(value):
    """
    Converts NaN/pandas/numpy values into JSON-safe values.
    """
    try:
        if pd.isna(value):
            return None
    except Exception:
        pass

    if hasattr(value, "item"):
        try:
            return value.item()
        except Exception:
            pass

    if isinstance(value, pd.Timestamp):
        return value.strftime("%Y-%m-%d")

    return value


def clean_records_for_json(records):
    """
    Makes dataframe records safe to save in JSON.
    """
    cleaned_records = []

    for row in records:
        cleaned_row = {}

        for key, value in row.items():
            cleaned_row[key] = clean_json_value(value)

        cleaned_records.append(cleaned_row)

    return cleaned_records


def load_matchup_cache():
    """
    Loads saved matchup cache from disk.
    """
    if not MATCHUP_CACHE_FILE.exists():
        return {}

    try:
        with open(MATCHUP_CACHE_FILE, "r") as file:
            return json.load(file)
    except Exception:
        return {}


def save_matchup_cache(cache):
    """
    Saves matchup cache to disk.
    """
    try:
        with open(MATCHUP_CACHE_FILE, "w") as file:
            json.dump(cache, file)
    except Exception:
        pass


def clear_matchup_cache():
    """
    Clears the local matchup cache file.
    """
    global MATCHUP_CACHE

    MATCHUP_CACHE = {}

    if MATCHUP_CACHE_FILE.exists():
        MATCHUP_CACHE_FILE.unlink()


MATCHUP_CACHE = load_matchup_cache()


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
    Pulls batter season stats from MLB Stats API.

    This is mainly used to get the batters for each team.
    The actual matchup tabs use:
    - batter vs pitcher stats
    - batter vs pitcher hand stats
    """
    file_path = CACHE_DIR / f"batters_{season}.csv"

    if file_path.exists() and cache_is_fresh(file_path) and not force_refresh:
        return pd.read_csv(file_path)

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

    df.to_csv(file_path, index=False)
    return df


def get_pitcher_stats(season, force_refresh=False):
    """
    Pulls pitcher season stats from MLB Stats API.
    Used for the pitcher strikeout matchup section.

    Important:
    This keeps both season workload and projected-start fields:
    - IP = season innings pitched
    - GS = games started
    - Pitches = season pitch count, if available
    """
    file_path = CACHE_DIR / f"pitchers_{season}.csv"

    if file_path.exists() and cache_is_fresh(file_path) and not force_refresh:
        return pd.read_csv(file_path)

    df = get_mlb_stats(season, "pitching")

    if df.empty:
        return pd.DataFrame()

    rename_cols = {
        "inningsPitched": "IP",
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

    # Some seasons/API responses may not include pitch count.
    # Keep the column anyway so scoring.py does not break.
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
        "ERA",
        "WHIP",
        "K/9",
        "BB/9",
        "SO",
        "BB",
        "BF"
    ]

    df = make_numeric(df, numeric_cols)

    # Do NOT force IP to numeric here because baseball IP can be written as:
    # 5.1 = 5 and 1/3 innings
    # 5.2 = 5 and 2/3 innings
    # scoring.py handles this conversion.

    df["K%"] = (df["SO"] / df["BF"]) * 100
    df["BB%"] = (df["BB"] / df["BF"]) * 100

    # MLB basic stats endpoint does not provide swinging strike percentage.
    df["SwStr%"] = None

    df = df.dropna(subset=["Name", "team_id"])

    df.to_csv(file_path, index=False)
    return df


def clean_stat_result(stat):
    """
    Converts MLB stat dictionary into clean matchup/split columns.
    Used for both:
    - batter vs pitcher
    - batter vs pitcher hand
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
    Pulls exact batter vs opposing pitcher matchup for the selected season.

    Uses local JSON cache so the same matchup does not get pulled every refresh.
    """
    if batter_id is None or pitcher_id is None:
        return clean_stat_result({})

    cache_key = f"bvp_{season}_{int(batter_id)}_{int(pitcher_id)}"

    if cache_key in MATCHUP_CACHE:
        return MATCHUP_CACHE[cache_key]

    params = {
        "stats": "vsPlayer",
        "group": "hitting",
        "opposingPlayerId": int(pitcher_id),
        "sportId": 1,
        "season": int(season)
    }

    try:
        response = requests.get(
            PLAYER_STATS_URL.format(int(batter_id)),
            params=params,
            timeout=20
        )

        response.raise_for_status()

        data = response.json()
        splits = data.get("stats", [{}])[0].get("splits", [])

        if not splits:
            result = clean_stat_result({})
        else:
            stat = splits[0].get("stat", {})
            result = clean_stat_result(stat)

    except Exception:
        result = clean_stat_result({})

    MATCHUP_CACHE[cache_key] = result
    save_matchup_cache(MATCHUP_CACHE)

    return result


def get_hitter_vs_hand_stats(batter_id, pitcher_hand, season):
    """
    Pulls hitter split against the opposing pitcher's throwing hand.

    R = hitter vs right-handed pitchers
    L = hitter vs left-handed pitchers

    Uses local JSON cache so the same split does not get pulled every refresh.
    """
    if batter_id is None or pitcher_hand not in ["R", "L"]:
        return clean_stat_result({})

    cache_key = f"hand_{season}_{int(batter_id)}_{pitcher_hand}"

    if cache_key in MATCHUP_CACHE:
        return MATCHUP_CACHE[cache_key]

    if pitcher_hand == "R":
        sit_code = "vr"
    else:
        sit_code = "vl"

    params = {
        "stats": "statSplits",
        "group": "hitting",
        "sitCodes": sit_code,
        "sportId": 1,
        "season": int(season)
    }

    try:
        response = requests.get(
            PLAYER_STATS_URL.format(int(batter_id)),
            params=params,
            timeout=20
        )

        response.raise_for_status()

        data = response.json()
        splits = data.get("stats", [{}])[0].get("splits", [])

        if not splits:
            result = clean_stat_result({})
        else:
            stat = splits[0].get("stat", {})
            result = clean_stat_result(stat)

    except Exception:
        result = clean_stat_result({})

    MATCHUP_CACHE[cache_key] = result
    save_matchup_cache(MATCHUP_CACHE)

    return result


def get_statcast_batter_vs_pitcher_pitches(batter_id, pitcher_id):
    """
    Pulls Statcast pitch-level data for one exact batter,
    then filters it to one exact pitcher.
    """
    batter_id = int(batter_id)
    pitcher_id = int(pitcher_id)

    start_year = 2015
    current_year = date.today().year

    all_years = []

    for year in range(start_year, current_year + 1):
        start_dt = f"{year}-03-01"

        if year == current_year:
            end_dt = date.today().strftime("%Y-%m-%d")
        else:
            end_dt = f"{year}-11-30"

        try:
            year_df = statcast_batter(
                start_dt=start_dt,
                end_dt=end_dt,
                player_id=batter_id
            )

            if year_df is None or year_df.empty:
                continue

            if "pitcher" not in year_df.columns:
                continue

            year_df["pitcher"] = pd.to_numeric(
                year_df["pitcher"],
                errors="coerce"
            )

            matchup_df = year_df[
                year_df["pitcher"] == pitcher_id
            ].copy()

            if not matchup_df.empty:
                all_years.append(matchup_df)

        except Exception:
            continue

    if not all_years:
        return pd.DataFrame()

    return pd.concat(all_years, ignore_index=True)


def get_terminal_pa_rows(statcast_df):
    """
    Converts pitch-level Statcast data into one row per plate appearance.

    Statcast has one row per pitch.
    A plate appearance ends on the row where 'events' is not blank.
    """
    if statcast_df.empty:
        return pd.DataFrame()

    df = statcast_df.copy()

    if "events" not in df.columns:
        return pd.DataFrame()

    df = df[df["events"].notna()].copy()

    if df.empty:
        return pd.DataFrame()

    df["batter"] = pd.to_numeric(df["batter"], errors="coerce")
    df["pitcher"] = pd.to_numeric(df["pitcher"], errors="coerce")

    if "game_date" in df.columns:
        df["game_date"] = pd.to_datetime(df["game_date"], errors="coerce")

    return df


def summarize_one_statcast_game(game_df):
    """
    Summarizes one game's actual batter-vs-pitcher matchup.
    """
    if game_df.empty:
        return {}

    game_df = game_df.copy()
    first_row = game_df.iloc[0]

    hit_events = ["single", "double", "triple", "home_run"]
    walk_events = ["walk", "intent_walk"]
    strikeout_events = ["strikeout", "strikeout_double_play"]
    hbp_events = ["hit_by_pitch"]

    non_ab_events = [
        "walk",
        "intent_walk",
        "hit_by_pitch",
        "sac_bunt",
        "sac_fly",
        "catcher_interf",
        "sac_fly_double_play",
        "sac_bunt_double_play"
    ]

    events = game_df["events"].fillna("").astype(str).str.lower()

    pa = len(game_df)
    ab = int((~events.isin(non_ab_events)).sum())
    h = int(events.isin(hit_events).sum())
    bb = int(events.isin(walk_events).sum())
    so = int(events.isin(strikeout_events).sum())
    hbp = int(events.isin(hbp_events).sum())
    hr = int((events == "home_run").sum())

    rbi = 0

    if "post_bat_score" in game_df.columns and "bat_score" in game_df.columns:
        post_scores = pd.to_numeric(game_df["post_bat_score"], errors="coerce")
        bat_scores = pd.to_numeric(game_df["bat_score"], errors="coerce")
        runs_added = post_scores - bat_scores
        rbi = int(runs_added.clip(lower=0).fillna(0).sum())

    total_bases = 0
    total_bases += int((events == "single").sum()) * 1
    total_bases += int((events == "double").sum()) * 2
    total_bases += int((events == "triple").sum()) * 3
    total_bases += int((events == "home_run").sum()) * 4

    avg = h / ab if ab > 0 else None
    obp = (h + bb + hbp) / pa if pa > 0 else None
    slg = total_bases / ab if ab > 0 else None
    ops = (obp + slg) if obp is not None and slg is not None else None

    k_rate = so / pa if pa > 0 else None
    bb_rate = bb / pa if pa > 0 else None

    inning_topbot = first_row.get("inning_topbot", None)
    home_team = first_row.get("home_team", None)
    away_team = first_row.get("away_team", None)

    if inning_topbot == "Top":
        team = away_team
        opponent = home_team
        home_away = "Away"
    elif inning_topbot == "Bot":
        team = home_team
        opponent = away_team
        home_away = "Home"
    else:
        team = None
        opponent = None
        home_away = None

    game_date = first_row.get("game_date", None)

    if pd.notna(game_date):
        try:
            game_date = pd.to_datetime(game_date).strftime("%Y-%m-%d")
        except Exception:
            game_date = str(game_date)

    return {
        "game_date": game_date,
        "game_pk": safe_int(first_row.get("game_pk")),
        "home_away": home_away,
        "team": team,
        "opponent": opponent,
        "PA": pa,
        "AB": ab,
        "H": h,
        "BB": bb,
        "HBP": hbp,
        "SO": so,
        "HR": hr,
        "RBI": rbi,
        "AVG": avg,
        "OBP": obp,
        "SLG": slg,
        "OPS": ops,
        "K%": k_rate * 100 if k_rate is not None else None,
        "BB%": bb_rate * 100 if bb_rate is not None else None,
    }


def get_batter_vs_pitcher_game_log(batter_id, pitcher_id, season=None):
    """
    Pulls career game-log history for one batter vs one pitcher.

    This uses Statcast pitch-level data from 2015-present.
    It only includes games where the selected batter faced the selected pitcher.
    """
    if batter_id is None or pitcher_id is None:
        return pd.DataFrame()

    batter_id = int(batter_id)
    pitcher_id = int(pitcher_id)

    cache_key = f"gamelog_career_pybaseball_{batter_id}_{pitcher_id}"

    if cache_key in MATCHUP_CACHE:
        return pd.DataFrame(MATCHUP_CACHE[cache_key])

    pitch_df = get_statcast_batter_vs_pitcher_pitches(
        batter_id=batter_id,
        pitcher_id=pitcher_id
    )

    pa_df = get_terminal_pa_rows(pitch_df)

    if pa_df.empty:
        MATCHUP_CACHE[cache_key] = []
        save_matchup_cache(MATCHUP_CACHE)
        return pd.DataFrame()

    rows = []

    for game_pk, game_df in pa_df.groupby("game_pk"):
        rows.append(summarize_one_statcast_game(game_df))

    result_df = pd.DataFrame(rows)

    if not result_df.empty and "game_date" in result_df.columns:
        result_df = result_df.sort_values("game_date", ascending=False)

    result = clean_records_for_json(
        result_df.to_dict(orient="records")
    )

    MATCHUP_CACHE[cache_key] = result
    save_matchup_cache(MATCHUP_CACHE)

    return pd.DataFrame(result)