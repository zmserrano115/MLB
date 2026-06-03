# src/matchups.py

import pandas as pd

from src.stat_data import (
    get_hitter_vs_pitcher_stats,
    get_hitter_vs_hand_stats
)

from src.scoring import (
    find_player_row,
    score_pitcher_k_matchup
)


def filter_team_players(df, team_id, min_pa=20):
    """
    Filters MLB Stats API player data by MLB team ID.
    """
    if df.empty or "team_id" not in df.columns:
        return pd.DataFrame()

    team_df = df[df["team_id"] == team_id].copy()

    if "PA" in team_df.columns:
        team_df = team_df[team_df["PA"] >= min_pa]

    return team_df


def grade_batter_row(row):
    """
    Grades based on the actual split/matchup row.
    """
    pa = row.get("PA", 0)
    obp = row.get("OBP", None)
    ops = row.get("OPS", None)

    if pa == 0:
        return "No History"

    if pa < 5:
        return "Small Sample"

    if pd.notna(obp) and pd.notna(ops):
        if obp >= 0.380 and ops >= 0.850:
            return "Strong"
        elif obp >= 0.330 and ops >= 0.750:
            return "Good"
        elif obp <= 0.280 or ops <= 0.650:
            return "Avoid"

    return "Neutral"


def build_batter_vs_pitcher_matchups(schedule_df, batters_df, season, min_pa=20):
    """
    Builds exact batter vs opposing probable pitcher table.
    """
    rows = []

    for _, game in schedule_df.iterrows():
        away_team = game["away_team"]
        home_team = game["home_team"]

        away_team_id = game["away_team_id"]
        home_team_id = game["home_team_id"]

        away_pitcher = game["away_probable_pitcher"]
        away_pitcher_id = game["away_probable_pitcher_id"]

        home_pitcher = game["home_probable_pitcher"]
        home_pitcher_id = game["home_probable_pitcher_id"]

        # Away hitters vs home pitcher
        away_hitters = filter_team_players(
            batters_df,
            away_team_id,
            min_pa=min_pa
        )

        for _, batter in away_hitters.iterrows():
            stats = get_hitter_vs_pitcher_stats(
                int(batter["player_id"]),
                int(home_pitcher_id) if pd.notna(home_pitcher_id) else None,
                int(season)
            )

            row = {
                "game": f"{away_team} @ {home_team}",
                "team": away_team,
                "batter": batter["Name"],
                "batter_id": batter["player_id"],
                "opposing_pitcher": home_pitcher,
                "opposing_pitcher_id": home_pitcher_id,
                "opposing_pitcher_hand": game["home_pitcher_hand"],
                "split": "Batter vs Pitcher"
            }

            row.update(stats)
            row["matchup_grade"] = grade_batter_row(row)
            rows.append(row)

        # Home hitters vs away pitcher
        home_hitters = filter_team_players(
            batters_df,
            home_team_id,
            min_pa=min_pa
        )

        for _, batter in home_hitters.iterrows():
            stats = get_hitter_vs_pitcher_stats(
                int(batter["player_id"]),
                int(away_pitcher_id) if pd.notna(away_pitcher_id) else None,
                int(season)
            )

            row = {
                "game": f"{away_team} @ {home_team}",
                "team": home_team,
                "batter": batter["Name"],
                "batter_id": batter["player_id"],
                "opposing_pitcher": away_pitcher,
                "opposing_pitcher_id": away_pitcher_id,
                "opposing_pitcher_hand": game["away_pitcher_hand"],
                "split": "Batter vs Pitcher"
            }

            row.update(stats)
            row["matchup_grade"] = grade_batter_row(row)
            rows.append(row)

    df = pd.DataFrame(rows)

    if df.empty:
        return df

    return df.sort_values(
        ["PA", "OBP", "OPS"],
        ascending=[False, False, False]
    )


def build_batter_vs_hand_matchups(schedule_df, batters_df, season, min_pa=20):
    """
    Builds hitter splits against the opposing pitcher's throwing hand.
    """
    rows = []

    for _, game in schedule_df.iterrows():
        away_team = game["away_team"]
        home_team = game["home_team"]

        away_team_id = game["away_team_id"]
        home_team_id = game["home_team_id"]

        away_pitcher = game["away_probable_pitcher"]
        away_pitcher_hand = game["away_pitcher_hand"]

        home_pitcher = game["home_probable_pitcher"]
        home_pitcher_hand = game["home_pitcher_hand"]

        # Away hitters vs home pitcher's hand
        away_hitters = filter_team_players(
            batters_df,
            away_team_id,
            min_pa=min_pa
        )

        for _, batter in away_hitters.iterrows():
            stats = get_hitter_vs_hand_stats(
                int(batter["player_id"]),
                home_pitcher_hand,
                int(season)
            )

            row = {
                "game": f"{away_team} @ {home_team}",
                "team": away_team,
                "batter": batter["Name"],
                "batter_id": batter["player_id"],
                "opposing_pitcher": home_pitcher,
                "opposing_pitcher_hand": home_pitcher_hand,
                "split": f"vs {home_pitcher_hand}HP"
            }

            row.update(stats)
            row["matchup_grade"] = grade_batter_row(row)
            rows.append(row)

        # Home hitters vs away pitcher's hand
        home_hitters = filter_team_players(
            batters_df,
            home_team_id,
            min_pa=min_pa
        )

        for _, batter in home_hitters.iterrows():
            stats = get_hitter_vs_hand_stats(
                int(batter["player_id"]),
                away_pitcher_hand,
                int(season)
            )

            row = {
                "game": f"{away_team} @ {home_team}",
                "team": home_team,
                "batter": batter["Name"],
                "batter_id": batter["player_id"],
                "opposing_pitcher": away_pitcher,
                "opposing_pitcher_hand": away_pitcher_hand,
                "split": f"vs {away_pitcher_hand}HP"
            }

            row.update(stats)
            row["matchup_grade"] = grade_batter_row(row)
            rows.append(row)

    df = pd.DataFrame(rows)

    if df.empty:
        return df

    return df.sort_values(
        ["OBP", "OPS", "PA"],
        ascending=[False, False, False]
    )


def build_pitcher_k_matchups(schedule_df, batters_df, pitchers_df, min_pa=20):
    """
    Builds pitcher strikeout matchup table.
    """
    rows = []

    for _, game in schedule_df.iterrows():
        away_team = game["away_team"]
        home_team = game["home_team"]

        away_team_id = game["away_team_id"]
        home_team_id = game["home_team_id"]

        away_pitcher_name = game["away_probable_pitcher"]
        home_pitcher_name = game["home_probable_pitcher"]

        away_pitcher_row = find_player_row(pitchers_df, away_pitcher_name)
        home_pitcher_row = find_player_row(pitchers_df, home_pitcher_name)

        home_batters = filter_team_players(
            batters_df,
            home_team_id,
            min_pa=min_pa
        )

        away_batters = filter_team_players(
            batters_df,
            away_team_id,
            min_pa=min_pa
        )

        away_k_matchup = score_pitcher_k_matchup(
            away_pitcher_row,
            home_batters
        )

        if away_k_matchup:
            away_k_matchup["game"] = f"{away_team} @ {home_team}"
            away_k_matchup["opponent"] = home_team
            away_k_matchup["pitcher_hand"] = game["away_pitcher_hand"]
            rows.append(away_k_matchup)

        home_k_matchup = score_pitcher_k_matchup(
            home_pitcher_row,
            away_batters
        )

        if home_k_matchup:
            home_k_matchup["game"] = f"{away_team} @ {home_team}"
            home_k_matchup["opponent"] = away_team
            home_k_matchup["pitcher_hand"] = game["home_pitcher_hand"]
            rows.append(home_k_matchup)

    if not rows:
        return pd.DataFrame()

    return pd.DataFrame(rows).sort_values(
        "k_matchup_score",
        ascending=False
    )


# Optional old-name compatibility
def build_hitter_matchups(schedule_df, batters_df, pitchers_df=None, min_pa=20, season=None):
    if season is None:
        return pd.DataFrame()

    return build_batter_vs_pitcher_matchups(
        schedule_df=schedule_df,
        batters_df=batters_df,
        season=season,
        min_pa=min_pa
    )