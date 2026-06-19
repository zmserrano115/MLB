# src/matchups.py

import pandas as pd

from src.matchup_grading import grade_hitter_matchup
from src.scoring import (
    find_player_row,
    grade_k_score,
    score_pitcher_k_matchup
)
from src.stat_data import (
    get_hitter_vs_pitcher_stats,
    get_hitter_vs_pitcher_stats_batch,
    get_hitter_vs_hand_stats
)

WEATHER_CONTEXT_COLUMNS = (
    "venue_name",
    "roof_type",
    "weather_icon",
    "weather_condition",
    "weather_display",
    "weather_tooltip",
    "weather_summary",
    "weather_edge",
    "temperature_f",
    "humidity_pct",
    "precip_probability_pct",
    "wind_speed_mph",
    "wind_direction_cardinal",
    "wind_field_direction",
    "wind_display",
    "wind_tooltip",
    "wind_out_mph",
    "hitter_weather_adjustment",
    "pitcher_weather_adjustment",
)

HITTER_GRADE_SCORES = {
    "Strong Matchup": 70.0,
    "Good Matchup": 60.0,
    "Neutral": 50.0,
    "Avoid": 40.0,
    "Small Sample": 20.0,
    "No History": 0.0,
}

HITTER_GRADE_ORDER = (
    "Avoid",
    "Neutral",
    "Good Matchup",
    "Strong Matchup",
)


def game_weather_context(game):
    return {
        column: game.get(column)
        for column in WEATHER_CONTEXT_COLUMNS
    }


def weather_adjusted_hitter_grade(history_grade, adjustment):
    if history_grade not in HITTER_GRADE_ORDER:
        return history_grade
    if history_grade == "Avoid":
        return history_grade

    adjustment = pd.to_numeric(adjustment, errors="coerce")
    if pd.isna(adjustment):
        return history_grade

    shift = 1 if adjustment >= 2.5 else -1 if adjustment <= -2.5 else 0
    index = HITTER_GRADE_ORDER.index(history_grade)
    index = max(0, min(len(HITTER_GRADE_ORDER) - 1, index + shift))
    adjusted_grade = HITTER_GRADE_ORDER[index]
    if adjusted_grade == "Strong Matchup" and history_grade != "Strong Matchup":
        return history_grade
    return adjusted_grade


def apply_hitter_weather_adjustment(result_df):
    result_df = result_df.copy()
    result_df["history_grade"] = result_df["matchup_grade"]
    adjustment_values = (
        result_df["hitter_weather_adjustment"]
        if "hitter_weather_adjustment" in result_df.columns
        else pd.Series(0.0, index=result_df.index)
    )
    adjustments = pd.to_numeric(
        adjustment_values,
        errors="coerce",
    ).fillna(0.0)
    base_scores = result_df["history_grade"].map(HITTER_GRADE_SCORES).fillna(0.0)
    result_df["weather_adjusted_score"] = (
        base_scores + adjustments
    ).clip(0.0, 100.0)
    result_df["matchup_grade"] = [
        weather_adjusted_hitter_grade(grade, adjustment)
        for grade, adjustment in zip(result_df["history_grade"], adjustments)
    ]
    return result_df


def apply_pitcher_weather_adjustment(score_row, game):
    base_score = pd.to_numeric(
        score_row.get("k_matchup_score"),
        errors="coerce",
    )
    adjustment = pd.to_numeric(
        game.get("pitcher_weather_adjustment", 0.0),
        errors="coerce",
    )
    if pd.isna(adjustment):
        adjustment = 0.0

    score_row["base_k_matchup_score"] = base_score
    score_row["weather_k_adjustment"] = float(adjustment)
    if not pd.isna(base_score):
        adjusted_score = max(0.0, min(100.0, float(base_score) + adjustment))
        score_row["k_matchup_score"] = adjusted_score
        score_row["k_matchup_grade"] = grade_k_score(adjusted_score)

    score_row.update(game_weather_context(game))
    return score_row


def get_team_batters(batters_df, team_id, min_pa=100, include_player_names=None):
    """
    Gets batters for one MLB team using team_id.
    """
    if batters_df.empty or team_id is None:
        return pd.DataFrame()

    df = batters_df.copy()

    if "team_id" not in df.columns:
        return pd.DataFrame()

    team_batters = df[df["team_id"] == team_id].copy()

    include_player_names = {
        str(name).strip().casefold()
        for name in (include_player_names or [])
        if str(name).strip()
    }

    if "PA" in team_batters.columns:
        team_batters["PA"] = pd.to_numeric(team_batters["PA"], errors="coerce")
        pa_mask = team_batters["PA"] >= min_pa
        if include_player_names and "Name" in team_batters.columns:
            include_mask = (
                team_batters["Name"]
                .fillna("")
                .astype(str)
                .str.strip()
                .str.casefold()
                .isin(include_player_names)
            )
            pa_mask = pa_mask | include_mask
        team_batters = team_batters[pa_mask].copy()

    return team_batters


def build_batter_vs_pitcher_matchups(
    schedule_df,
    batters_df,
    season,
    min_pa=100,
    include_batter_names=None,
):
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
            min_pa=min_pa,
            include_player_names=include_batter_names,
        )

        for _, batter in home_batters.iterrows():
            batter_id = batter.get("player_id")
            
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

            row.update(game_weather_context(game))
            rows.append(row)

        # Away batters face home pitcher
        away_batters = get_team_batters(
            batters_df=batters_df,
            team_id=away_team_id,
            min_pa=min_pa,
            include_player_names=include_batter_names,
        )

        for _, batter in away_batters.iterrows():
            batter_id = batter.get("player_id")

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

            row.update(game_weather_context(game))
            rows.append(row)

    stats_by_pair = get_hitter_vs_pitcher_stats_batch(
        [
            (row.get("batter_id"), row.get("opposing_pitcher_id"))
            for row in rows
        ],
        season=season,
    )
    for row in rows:
        pair = (row.get("batter_id"), row.get("opposing_pitcher_id"))
        stats = stats_by_pair.get(pair)
        if stats is None:
            stats = get_hitter_vs_pitcher_stats(
                batter_id=row.get("batter_id"),
                pitcher_id=row.get("opposing_pitcher_id"),
                season=season,
            )
        row.update(stats)

    result_df = pd.DataFrame(rows)

    if result_df.empty:
        return result_df

    result_df["PA"] = pd.to_numeric(result_df["PA"], errors="coerce").fillna(0)
    result_df["AB"] = pd.to_numeric(result_df["AB"], errors="coerce").fillna(0)
    result_df["AVG"] = pd.to_numeric(result_df["AVG"], errors="coerce").fillna(0)
    result_df["matchup_grade"] = [
        grade_hitter_matchup(at_bats, batting_average)
        for at_bats, batting_average in zip(result_df["AB"], result_df["AVG"])
    ]

    result_df = apply_hitter_weather_adjustment(result_df)
    result_df = result_df.sort_values(
        by=["weather_adjusted_score", "AB", "AVG", "H"],
        ascending=[False, False, False, False]
    )

    return result_df


def build_batter_vs_hand_matchups(
    schedule_df,
    batters_df,
    season,
    min_pa=100,
    include_batter_names=None,
):
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
            min_pa=min_pa,
            include_player_names=include_batter_names,
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
            row.update(game_weather_context(game))
            rows.append(row)

        # Away batters vs home pitcher hand
        away_batters = get_team_batters(
            batters_df=batters_df,
            team_id=away_team_id,
            min_pa=min_pa,
            include_player_names=include_batter_names,
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
            row.update(game_weather_context(game))
            rows.append(row)

    result_df = pd.DataFrame(rows)

    if result_df.empty:
        return result_df

    result_df["PA"] = pd.to_numeric(result_df["PA"], errors="coerce").fillna(0)
    result_df["AB"] = pd.to_numeric(result_df["AB"], errors="coerce").fillna(0)
    result_df["AVG"] = pd.to_numeric(result_df["AVG"], errors="coerce").fillna(0)
    result_df["matchup_grade"] = [
        grade_hitter_matchup(at_bats, batting_average)
        for at_bats, batting_average in zip(result_df["AB"], result_df["AVG"])
    ]

    result_df = apply_hitter_weather_adjustment(result_df)
    result_df = result_df.sort_values(
        by=["weather_adjusted_score", "AB", "AVG", "H"],
        ascending=[False, False, False, False]
    )

    return result_df


def build_pitcher_k_matchups(
    schedule_df,
    batters_df,
    pitchers_df,
    min_pa=100,
    include_batter_names=None,
):
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
            min_pa=min_pa,
            include_player_names=include_batter_names,
        )

        if away_pitcher_row is not None and not home_batters.empty:
            score_row = score_pitcher_k_matchup(
                pitcher_row=away_pitcher_row,
                opposing_batters=home_batters
            )

            if score_row is not None:
                score_row = apply_pitcher_weather_adjustment(score_row, game)
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
            min_pa=min_pa,
            include_player_names=include_batter_names,
        )

        if home_pitcher_row is not None and not away_batters.empty:
            score_row = score_pitcher_k_matchup(
                pitcher_row=home_pitcher_row,
                opposing_batters=away_batters
            )

            if score_row is not None:
                score_row = apply_pitcher_weather_adjustment(score_row, game)
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
