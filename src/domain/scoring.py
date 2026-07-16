"""Pure pitcher matchup scoring calculations."""

import re

import numpy as np
import pandas as pd


def normalize_name(name):
    if pd.isna(name):
        return ""

    name = str(name).lower()
    name = re.sub(r"[^a-z\s]", "", name)
    name = re.sub(r"\s+", " ", name).strip()
    return name


def safe_number(value, default=np.nan):
    value = pd.to_numeric(value, errors="coerce")

    if pd.isna(value):
        return default

    return float(value)


def scale_value(value, low, high):
    value = safe_number(value)

    if pd.isna(value):
        return 50

    score = ((value - low) / (high - low)) * 100
    return max(0, min(100, score))


def find_player_row(df, player_name):
    if player_name is None or pd.isna(player_name):
        return None

    target = normalize_name(player_name)

    df = df.copy()

    if "name_key" not in df.columns:
        df["name_key"] = df["Name"].apply(normalize_name)

    exact = df[df["name_key"] == target]

    if not exact.empty:
        return exact.iloc[0]

    partial = df[df["name_key"].str.contains(target, na=False)]

    if not partial.empty:
        return partial.iloc[0]

    reverse_partial = df[
        df["name_key"].apply(lambda x: x in target if isinstance(x, str) else False)
    ]

    if not reverse_partial.empty:
        return reverse_partial.iloc[0]

    return None


def parse_baseball_ip(ip_value):
    """
    Converts baseball innings format into true decimal innings.

    Examples:
    5.1 = 5 and 1/3 innings
    5.2 = 5 and 2/3 innings
    """
    if pd.isna(ip_value):
        return np.nan

    ip_str = str(ip_value).strip()

    if "." not in ip_str:
        return safe_number(ip_str)

    whole, partial = ip_str.split(".", 1)

    whole = safe_number(whole, default=0)

    if partial == "1":
        return whole + (1 / 3)
    elif partial == "2":
        return whole + (2 / 3)
    else:
        return safe_number(ip_value)


def estimate_projected_ip(pitcher_row):
    """
    Estimates today's likely innings for a starting pitcher.

    This prevents season IP, like 60 IP, from being treated as today's workload.
    """
    season_ip = parse_baseball_ip(pitcher_row.get("IP", np.nan))
    games_started = safe_number(pitcher_row.get("GS", np.nan))

    if pd.isna(season_ip) or pd.isna(games_started) or games_started <= 0:
        return 5.0

    avg_ip_per_start = season_ip / games_started

    # Realistic starter range for one game.
    projected_ip = max(3.0, min(6.5, avg_ip_per_start))

    return projected_ip


def estimate_projected_pitch_count(pitcher_row):
    """
    Estimates today's likely pitch count.

    If season pitches are available:
        pitches / games started

    If not:
        projected IP * 15.5 pitches per inning
    """
    pitches = safe_number(pitcher_row.get("Pitches", np.nan))
    games_started = safe_number(pitcher_row.get("GS", np.nan))

    if not pd.isna(pitches) and not pd.isna(games_started) and games_started > 0:
        avg_pitches = pitches / games_started
        return max(55, min(105, avg_pitches))

    projected_ip = estimate_projected_ip(pitcher_row)
    estimated_pitches = projected_ip * 15.5

    return max(55, min(105, estimated_pitches))


def grade_k_score(score):
    if score >= 75:
        return "Elite K Matchup"
    elif score >= 65:
        return "Strong K Matchup"
    elif score >= 55:
        return "Good K Matchup"
    elif score >= 45:
        return "Neutral"
    else:
        return "Avoid"


def score_pitcher_k_matchup(pitcher_row, opposing_batters):
    """
    Scores one probable pitcher against the opposing team's hitters.

    This uses:
    - projected innings for today's start
    - projected pitch count
    - projected strikeouts
    - pitcher K ability
    - opponent hitter K tendency
    """
    if pitcher_row is None or opposing_batters.empty:
        return None

    pitcher_k_pct = safe_number(pitcher_row.get("K%", np.nan))
    pitcher_k9 = safe_number(pitcher_row.get("K/9", np.nan))
    pitcher_swstr = safe_number(pitcher_row.get("SwStr%", np.nan))

    season_ip = parse_baseball_ip(pitcher_row.get("IP", np.nan))
    games_started = safe_number(pitcher_row.get("GS", np.nan))

    projected_ip = estimate_projected_ip(pitcher_row)
    projected_pitch_count = estimate_projected_pitch_count(pitcher_row)

    opponent_avg_k_pct = safe_number(opposing_batters["K%"].mean())
    opponent_avg = (
        safe_number(opposing_batters["AVG"].mean()) if "AVG" in opposing_batters.columns else np.nan
    )

    pitcher_k_score = scale_value(pitcher_k_pct, 18, 35)
    pitcher_k9_score = scale_value(pitcher_k9, 6.5, 12.5)

    swstr_score = 50 if pd.isna(pitcher_swstr) else scale_value(pitcher_swstr, 8, 17)

    opponent_k_score = scale_value(opponent_avg_k_pct, 18, 30)

    final_score = (
        pitcher_k_score * 0.40
        + pitcher_k9_score * 0.25
        + swstr_score * 0.15
        + opponent_k_score * 0.20
    )

    opponent_k_adjustment = 1

    if not pd.isna(opponent_avg_k_pct):
        opponent_k_adjustment = opponent_avg_k_pct / 22

    if pd.isna(pitcher_k9):
        projected_ks = np.nan
    else:
        projected_ks = (pitcher_k9 * projected_ip / 9) * opponent_k_adjustment

    pitcher_hits = safe_number(pitcher_row.get("H", np.nan))
    if pd.isna(pitcher_hits) or pd.isna(season_ip) or season_ip <= 0:
        projected_hits = np.nan
    else:
        opponent_hit_adjustment = 1.0
        if not pd.isna(opponent_avg):
            opponent_hit_adjustment = max(0.75, min(1.25, opponent_avg / 0.245))
        projected_hits = (pitcher_hits / season_ip) * projected_ip * opponent_hit_adjustment

    return {
        "pitcher_id": pitcher_row.get("player_id"),
        "pitcher": pitcher_row.get("Name"),
        "pitcher_team": pitcher_row.get("Team"),
        "Season IP": season_ip,
        "GS": games_started,
        "Projected IP": projected_ip,
        "Projected Pitch Count": projected_pitch_count,
        "Projected Ks": projected_ks,
        "Projected Hits": projected_hits,
        "ERA": pitcher_row.get("ERA"),
        "WHIP": pitcher_row.get("WHIP"),
        "K%": pitcher_k_pct,
        "K/9": pitcher_k9,
        "SwStr%": pitcher_swstr,
        "opponent_avg_k%": opponent_avg_k_pct,
        "k_matchup_score": final_score,
        "k_matchup_grade": grade_k_score(final_score),
    }
