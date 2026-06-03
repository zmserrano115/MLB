# src/scoring.py

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


def scale_between(value, low, high):
    return ((value - low) / (high - low) * 100).clip(0, 100)


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

    reverse_partial = df[df["name_key"].apply(lambda x: x in target if isinstance(x, str) else False)]

    if not reverse_partial.empty:
        return reverse_partial.iloc[0]

    return None


def grade_hitter_score(score):
    if score >= 75:
        return "Elite Matchup"
    elif score >= 65:
        return "Strong Matchup"
    elif score >= 55:
        return "Good Matchup"
    elif score >= 45:
        return "Neutral"
    else:
        return "Avoid"


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


def score_hitter_matchups(batter_df, opposing_pitcher_row=None):
    df = batter_df.copy()

    for col in ["AVG", "OBP", "OPS", "wOBA", "K%"]:
        if col not in df.columns:
            df[col] = np.nan

    avg_score = scale_between(df["AVG"], 0.220, 0.320)
    obp_score = scale_between(df["OBP"], 0.290, 0.400)
    ops_score = scale_between(df["OPS"], 0.650, 0.950)
    woba_score = scale_between(df["wOBA"], 0.290, 0.400)

    contact_score = 100 - scale_between(df["K%"], 15, 32)

    hitter_ability_score = (
        avg_score * 0.20 +
        obp_score * 0.30 +
        ops_score * 0.20 +
        woba_score * 0.20 +
        contact_score * 0.10
    )

    pitcher_weakness_score = 50

    if opposing_pitcher_row is not None:
        pitcher_era = opposing_pitcher_row.get("ERA", np.nan)
        pitcher_whip = opposing_pitcher_row.get("WHIP", np.nan)
        pitcher_k_pct = opposing_pitcher_row.get("K%", np.nan)

        era_score = scale_between(pd.Series([pitcher_era]), 2.50, 5.50).iloc[0]
        whip_score = scale_between(pd.Series([pitcher_whip]), 0.95, 1.50).iloc[0]

        pitcher_low_k_score = 100 - scale_between(pd.Series([pitcher_k_pct]), 18, 32).iloc[0]

        pitcher_weakness_score = np.nanmean([
            era_score,
            whip_score,
            pitcher_low_k_score
        ])

    df["hitter_ability_score"] = hitter_ability_score
    df["pitcher_weakness_score"] = pitcher_weakness_score

    df["matchup_score"] = (
        df["hitter_ability_score"] * 0.75 +
        df["pitcher_weakness_score"] * 0.25
    )

    df["matchup_grade"] = df["matchup_score"].apply(grade_hitter_score)

    return df.sort_values("matchup_score", ascending=False)


def score_pitcher_k_matchup(pitcher_row, opposing_batters):
    if pitcher_row is None or opposing_batters.empty:
        return None

    pitcher_k_pct = pitcher_row.get("K%", np.nan)
    pitcher_k9 = pitcher_row.get("K/9", np.nan)
    pitcher_swstr = pitcher_row.get("SwStr%", np.nan)

    opponent_avg_k_pct = opposing_batters["K%"].mean()

    pitcher_k_score = scale_between(pd.Series([pitcher_k_pct]), 18, 35).iloc[0]
    pitcher_k9_score = scale_between(pd.Series([pitcher_k9]), 6.5, 12.5).iloc[0]

    if pd.isna(pitcher_swstr):
        swstr_score = 50
    else:
        swstr_score = scale_between(pd.Series([pitcher_swstr]), 8, 17).iloc[0]

    opponent_k_score = scale_between(pd.Series([opponent_avg_k_pct]), 18, 30).iloc[0]

    final_score = (
        pitcher_k_score * 0.40 +
        pitcher_k9_score * 0.25 +
        swstr_score * 0.15 +
        opponent_k_score * 0.20
    )

    return {
        "pitcher": pitcher_row.get("Name"),
        "pitcher_team": pitcher_row.get("Team"),
        "IP": pitcher_row.get("IP"),
        "ERA": pitcher_row.get("ERA"),
        "WHIP": pitcher_row.get("WHIP"),
        "K%": pitcher_k_pct,
        "K/9": pitcher_k9,
        "SwStr%": pitcher_swstr,
        "opponent_avg_k%": opponent_avg_k_pct,
        "k_matchup_score": final_score,
        "k_matchup_grade": grade_k_score(final_score),
    }