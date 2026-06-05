# src/matchups.py

import pandas as pd

from src.scoring import (
    find_player_row,
    score_hitter_matchups,
    score_pitcher_k_matchup
)
from src.stat_data import (
    get_hitter_vs_pitcher_stats,
    get_hitter_vs_hand_stats
)


def get_team_batters(batters_df, team_id, min_pa=100):
    """
    Gets batters for one MLB team using team_id.
    """
    if batters_df.empty or team_id is None:
        return pd.DataFrame()

    df = batters_df.copy()

    if "team_id" not in df.columns:
        return pd.DataFrame()

    team_batters = df[df["team_id"] == team_id].copy()

    if "PA" in team_batters.columns:
        team_batters["PA"] = pd.to_numeric(team_batters["PA"], errors="coerce")
        team_batters = team_batters[team_batters["PA"] >= min_pa].copy()

    return team_batters


def build_batter_vs_pitcher_matchups(schedule_df, batters_df, season, min_pa=100):
    """
    Builds hitter rows based on direct batter-vs-opposing-pitcher history.
    """
    rows = []

    if schedule_df.empty or batters_df.empty:
        return pd.DataFrame()

    for _, game in schedule_df.iterrows():
        away_team = game.get("away_team")
        home_team = game.get("home_team")
        away_team_id = game.get("away_team_id")
        home_team_id = game.get("home_team_id")

        away_pitcher = game.get("away_probable_pitcher")
        home_pitcher = game.get("home_probable_pitcher")

        away_pitcher_id = game.get("away_probable_pitcher_id")
        home_pitcher_id = game.get("home_probable_pitcher_id")

        away_pitcher_hand = game.get("away_pitcher_hand")
        home_pitcher_hand = game.get("home_pitcher_hand")

        game_name = f"{away_team} @ {home_team}"

        # Home batters face away pitcher
        home_batters = get_team_batters(
            batters_df=batters_df,
            team_id=home_team_id,
            min_pa=min_pa
        )

        for _, batter in home_batters.iterrows():
            batter_id = batter.get("player_id")

            stats = get_hitter_vs_pitcher_stats(
                batter_id=batter_id,
                pitcher_id=away_pitcher_id,
                season=season
            )

            row = {
                "game": game_name,
                "team": home_team,
                "batter_id": batter_id,
                "batter": batter.get("Name"),
                "opposing_pitcher_id": away_pitcher_id,
                "opposing_pitcher": away_pitcher,
                "opposing_pitcher_hand": away_pitcher_hand,
                "split": "Batter vs Pitcher"
            }

            row.update(stats)
            rows.append(row)

        # Away batters face home pitcher
        away_batters = get_team_batters(
            batters_df=batters_df,
            team_id=away_team_id,
            min_pa=min_pa
        )

        for _, batter in away_batters.iterrows():
            batter_id = batter.get("player_id")

            stats = get_hitter_vs_pitcher_stats(
                batter_id=batter_id,
                pitcher_id=home_pitcher_id,
                season=season
            )

            row = {
                "game": game_name,
                "team": away_team,
                "batter_id": batter_id,
                "batter": batter.get("Name"),
                "opposing_pitcher_id": home_pitcher_id,
                "opposing_pitcher": home_pitcher,
                "opposing_pitcher_hand": home_pitcher_hand,
                "split": "Batter vs Pitcher"
            }

            row.update(stats)
            rows.append(row)

    result_df = pd.DataFrame(rows)

    if result_df.empty:
        return result_df

    result_df["PA"] = pd.to_numeric(result_df["PA"], errors="coerce").fillna(0)

    # Grade direct BvP results with simple sample-aware labels.
    result_df["matchup_grade"] = "No History"

    result_df.loc[
        (result_df["PA"] > 0) & (result_df["PA"] < 5),
        "matchup_grade"
    ] = "Small Sample"

    result_df.loc[
        (result_df["PA"] >= 5) & (result_df["OBP"] >= 0.360),
        "matchup_grade"
    ] = "Strong Matchup"

    result_df.loc[
        (result_df["PA"] >= 5) & (result_df["OBP"] >= 0.320) & (result_df["OBP"] < 0.360),
        "matchup_grade"
    ] = "Good Matchup"

    result_df.loc[
        (result_df["PA"] >= 5) & (result_df["OBP"] >= 0.280) & (result_df["OBP"] < 0.320),
        "matchup_grade"
    ] = "Neutral"

    result_df.loc[
        (result_df["PA"] >= 5) & (result_df["OBP"] < 0.280),
        "matchup_grade"
    ] = "Avoid"

    result_df = result_df.sort_values(
        by=["PA", "OBP", "OPS"],
        ascending=[False, False, False]
    )

    return result_df


def build_batter_vs_hand_matchups(schedule_df, batters_df, season, min_pa=100):
    """
    Builds hitter rows based on splits against the opposing pitcher's throwing hand.
    """
    rows = []

    if schedule_df.empty or batters_df.empty:
        return pd.DataFrame()

    for _, game in schedule_df.iterrows():
        away_team = game.get("away_team")
        home_team = game.get("home_team")
        away_team_id = game.get("away_team_id")
        home_team_id = game.get("home_team_id")

        away_pitcher = game.get("away_probable_pitcher")
        home_pitcher = game.get("home_probable_pitcher")

        away_pitcher_id = game.get("away_probable_pitcher_id")
        home_pitcher_id = game.get("home_probable_pitcher_id")

        away_pitcher_hand = game.get("away_pitcher_hand")
        home_pitcher_hand = game.get("home_pitcher_hand")

        game_name = f"{away_team} @ {home_team}"

        # Home batters vs away pitcher hand
        home_batters = get_team_batters(
            batters_df=batters_df,
            team_id=home_team_id,
            min_pa=min_pa
        )

        for _, batter in home_batters.iterrows():
            batter_id = batter.get("player_id")

            stats = get_hitter_vs_hand_stats(
                batter_id=batter_id,
                pitcher_hand=away_pitcher_hand,
                season=season
            )

            row = {
                "game": game_name,
                "team": home_team,
                "batter_id": batter_id,
                "batter": batter.get("Name"),
                "opposing_pitcher_id": away_pitcher_id,
                "opposing_pitcher": away_pitcher,
                "opposing_pitcher_hand": away_pitcher_hand,
                "split": f"vs {away_pitcher_hand}HP"
            }

            row.update(stats)
            rows.append(row)

        # Away batters vs home pitcher hand
        away_batters = get_team_batters(
            batters_df=batters_df,
            team_id=away_team_id,
            min_pa=min_pa
        )

        for _, batter in away_batters.iterrows():
            batter_id = batter.get("player_id")

            stats = get_hitter_vs_hand_stats(
                batter_id=batter_id,
                pitcher_hand=home_pitcher_hand,
                season=season
            )

            row = {
                "game": game_name,
                "team": away_team,
                "batter_id": batter_id,
                "batter": batter.get("Name"),
                "opposing_pitcher_id": home_pitcher_id,
                "opposing_pitcher": home_pitcher,
                "opposing_pitcher_hand": home_pitcher_hand,
                "split": f"vs {home_pitcher_hand}HP"
            }

            row.update(stats)
            rows.append(row)

    result_df = pd.DataFrame(rows)

    if result_df.empty:
        return result_df

    result_df["PA"] = pd.to_numeric(result_df["PA"], errors="coerce").fillna(0)
    result_df["OBP"] = pd.to_numeric(result_df["OBP"], errors="coerce")
    result_df["OPS"] = pd.to_numeric(result_df["OPS"], errors="coerce")

    result_df["matchup_grade"] = "No History"

    result_df.loc[
        (result_df["PA"] > 0) & (result_df["PA"] < 20),
        "matchup_grade"
    ] = "Small Sample"

    result_df.loc[
        (result_df["PA"] >= 20) & (result_df["OBP"] >= 0.360),
        "matchup_grade"
    ] = "Strong Matchup"

    result_df.loc[
        (result_df["PA"] >= 20) & (result_df["OBP"] >= 0.320) & (result_df["OBP"] < 0.360),
        "matchup_grade"
    ] = "Good Matchup"

    result_df.loc[
        (result_df["PA"] >= 20) & (result_df["OBP"] >= 0.280) & (result_df["OBP"] < 0.320),
        "matchup_grade"
    ] = "Neutral"

    result_df.loc[
        (result_df["PA"] >= 20) & (result_df["OBP"] < 0.280),
        "matchup_grade"
    ] = "Avoid"

    result_df = result_df.sort_values(
        by=["OBP", "OPS", "PA"],
        ascending=[False, False, False]
    )

    return result_df


def build_pitcher_k_matchups(schedule_df, batters_df, pitchers_df, min_pa=100):
    """
    Builds strikeout matchup rows for today's probable pitchers.

    IMPORTANT:
    This version keeps pitcher_id in the final output so the app can
    load a pitcher-vs-opponent career game log when a row is clicked.
    """
    rows = []

    if schedule_df.empty or batters_df.empty or pitchers_df.empty:
        return pd.DataFrame()

    for _, game in schedule_df.iterrows():
        away_team = game.get("away_team")
        home_team = game.get("home_team")
        away_team_id = game.get("away_team_id")
        home_team_id = game.get("home_team_id")

        away_pitcher_name = game.get("away_probable_pitcher")
        home_pitcher_name = game.get("home_probable_pitcher")

        away_pitcher_hand = game.get("away_pitcher_hand")
        home_pitcher_hand = game.get("home_pitcher_hand")

        game_name = f"{away_team} @ {home_team}"

        # Away pitcher faces home batters
        away_pitcher_row = find_player_row(
            pitchers_df,
            away_pitcher_name
        )

        home_batters = get_team_batters(
            batters_df=batters_df,
            team_id=home_team_id,
            min_pa=min_pa
        )

        if away_pitcher_row is not None and not home_batters.empty:
            score_row = score_pitcher_k_matchup(
                pitcher_row=away_pitcher_row,
                opposing_batters=home_batters
            )

            if score_row is not None:
                score_row["game"] = game_name
                score_row["pitcher_id"] = away_pitcher_row.get("player_id")
                score_row["pitcher"] = away_pitcher_row.get("Name")
                score_row["pitcher_team"] = away_team
                score_row["pitcher_hand"] = away_pitcher_hand
                score_row["opponent"] = home_team
                rows.append(score_row)

        # Home pitcher faces away batters
        home_pitcher_row = find_player_row(
            pitchers_df,
            home_pitcher_name
        )

        away_batters = get_team_batters(
            batters_df=batters_df,
            team_id=away_team_id,
            min_pa=min_pa
        )

        if home_pitcher_row is not None and not away_batters.empty:
            score_row = score_pitcher_k_matchup(
                pitcher_row=home_pitcher_row,
                opposing_batters=away_batters
            )

            if score_row is not None:
                score_row["game"] = game_name
                score_row["pitcher_id"] = home_pitcher_row.get("player_id")
                score_row["pitcher"] = home_pitcher_row.get("Name")
                score_row["pitcher_team"] = home_team
                score_row["pitcher_hand"] = home_pitcher_hand
                score_row["opponent"] = away_team
                rows.append(score_row)

    result_df = pd.DataFrame(rows)

    if result_df.empty:
        return result_df

    if "k_matchup_score" in result_df.columns:
        result_df = result_df.sort_values(
            "k_matchup_score",
            ascending=False
        )

    return result_df