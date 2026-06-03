# refresh_nightly.py

from datetime import date, datetime
from pathlib import Path
import argparse
import traceback
import json

from src.mlb_schedule import get_daily_schedule
from src.stat_data import (
    get_batter_stats,
    get_pitcher_stats,
    clear_matchup_cache,
    get_batter_vs_pitcher_game_log
)
from src.matchups import (
    build_batter_vs_pitcher_matchups,
    build_batter_vs_hand_matchups,
    build_pitcher_k_matchups
)


DATA_DIR = Path("data")
DATA_DIR.mkdir(exist_ok=True)

PRECOMPUTED_DIR = DATA_DIR / "precomputed"
PRECOMPUTED_DIR.mkdir(exist_ok=True)

LOG_FILE = DATA_DIR / "nightly_refresh_log.txt"


def write_log(message):
    """
    Writes progress messages to the terminal and to a log file.
    """
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    full_message = f"[{timestamp}] {message}"

    print(full_message)

    with open(LOG_FILE, "a", encoding="utf-8") as file:
        file.write(full_message + "\n")


def save_dataframe(df, file_name):
    """
    Saves a dataframe to data/precomputed.
    """
    file_path = PRECOMPUTED_DIR / file_name

    if df is None or df.empty:
        file_path.write_text("", encoding="utf-8")
        return

    df.to_csv(file_path, index=False)


def save_metadata(
    game_date,
    season,
    min_pa,
    schedule_rows,
    bvp_rows,
    hand_rows,
    k_rows,
    game_logs_built
):
    """
    Saves refresh information so the app/user can see when data was last updated.
    """
    metadata = {
        "last_refreshed": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "game_date": game_date,
        "season": season,
        "minimum_pa": min_pa,
        "schedule_rows": schedule_rows,
        "batter_vs_pitcher_rows": bvp_rows,
        "batter_vs_hand_rows": hand_rows,
        "pitcher_k_rows": k_rows,
        "game_logs_preloaded": game_logs_built
    }

    metadata_path = PRECOMPUTED_DIR / "latest_metadata.json"

    with open(metadata_path, "w", encoding="utf-8") as file:
        json.dump(metadata, file, indent=4)


def build_precomputed_game_logs(bvp_matchups, season, max_game_logs):
    """
    Preloads career game logs for Batter vs Pitcher matchups with history.

    This makes the Streamlit Cloud app faster because clicked game logs
    can load from data/matchup_cache.json instead of pulling live.
    """
    if bvp_matchups is None or bvp_matchups.empty:
        write_log("No BvP matchups available for game-log preloading.")
        return 0

    required_cols = [
        "batter",
        "batter_id",
        "opposing_pitcher",
        "opposing_pitcher_id",
        "PA"
    ]

    missing_cols = [
        col for col in required_cols if col not in bvp_matchups.columns
    ]

    if missing_cols:
        write_log(f"Skipping game-log preload. Missing columns: {missing_cols}")
        return 0

    matchups_with_history = bvp_matchups[
        bvp_matchups["PA"] > 0
    ].copy()

    if matchups_with_history.empty:
        write_log("No BvP rows with PA > 0. No game logs to preload.")
        return 0

    matchups_with_history = matchups_with_history.sort_values(
        "PA",
        ascending=False
    )

    matchups_to_build = matchups_with_history.head(max_game_logs)

    write_log(
        f"Preloading {len(matchups_to_build)} career BvP game logs "
        f"out of {len(matchups_with_history)} matchups with history."
    )

    built_count = 0

    for _, row in matchups_to_build.iterrows():
        batter = row.get("batter")
        pitcher = row.get("opposing_pitcher")
        batter_id = row.get("batter_id")
        pitcher_id = row.get("opposing_pitcher_id")

        if batter_id is None or pitcher_id is None:
            continue

        write_log(f"Preloading game log: {batter} vs {pitcher}")

        game_log_df = get_batter_vs_pitcher_game_log(
            batter_id=int(batter_id),
            pitcher_id=int(pitcher_id),
            season=season
        )

        if game_log_df is not None and not game_log_df.empty:
            built_count += 1

    write_log(f"Career game logs successfully preloaded: {built_count}")

    return built_count


def run_nightly_refresh(
    game_date,
    season,
    min_pa=100,
    build_game_logs=True,
    max_game_logs=50
):
    """
    Refreshes MLB matchup data.

    This script is meant to run locally or through GitHub Actions.
    """

    write_log("========================================")
    write_log("Starting nightly MLB data refresh")
    write_log(f"Game date: {game_date}")
    write_log(f"Season: {season}")
    write_log(f"Minimum PA: {min_pa}")
    write_log(f"Build game logs: {build_game_logs}")
    write_log(f"Max game logs: {max_game_logs}")

    write_log("Pulling daily schedule...")
    schedule_df = get_daily_schedule(game_date)

    if schedule_df.empty:
        write_log("No games found for this date. Saving metadata and stopping.")

        save_metadata(
            game_date=game_date,
            season=season,
            min_pa=min_pa,
            schedule_rows=0,
            bvp_rows=0,
            hand_rows=0,
            k_rows=0,
            game_logs_built=0
        )

        return

    write_log(f"Games found: {len(schedule_df)}")

    write_log("Refreshing batter season stats...")
    batters_df = get_batter_stats(season, force_refresh=True)
    write_log(f"Batter rows loaded: {len(batters_df)}")

    write_log("Refreshing pitcher season stats...")
    pitchers_df = get_pitcher_stats(season, force_refresh=True)
    write_log(f"Pitcher rows loaded: {len(pitchers_df)}")

    write_log("Clearing old matchup cache...")
    clear_matchup_cache()

    write_log("Building batter vs opposing pitcher matchups...")
    bvp_matchups = build_batter_vs_pitcher_matchups(
        schedule_df=schedule_df,
        batters_df=batters_df,
        season=season,
        min_pa=min_pa
    )
    write_log(f"Batter vs pitcher rows built: {len(bvp_matchups)}")

    write_log("Building batter vs pitcher-hand matchups...")
    hand_matchups = build_batter_vs_hand_matchups(
        schedule_df=schedule_df,
        batters_df=batters_df,
        season=season,
        min_pa=min_pa
    )
    write_log(f"Batter vs hand rows built: {len(hand_matchups)}")

    write_log("Building pitcher strikeout matchups...")
    pitcher_k_matchups = build_pitcher_k_matchups(
        schedule_df=schedule_df,
        batters_df=batters_df,
        pitchers_df=pitchers_df,
        min_pa=min_pa
    )
    write_log(f"Pitcher K matchup rows built: {len(pitcher_k_matchups)}")

    game_logs_built = 0

    if build_game_logs:
        game_logs_built = build_precomputed_game_logs(
            bvp_matchups=bvp_matchups,
            season=season,
            max_game_logs=max_game_logs
        )

    write_log("Saving precomputed data files...")
    save_dataframe(schedule_df, "latest_schedule.csv")
    save_dataframe(bvp_matchups, "latest_batter_vs_pitcher.csv")
    save_dataframe(hand_matchups, "latest_batter_vs_hand.csv")
    save_dataframe(pitcher_k_matchups, "latest_pitcher_k_matchups.csv")

    save_metadata(
        game_date=game_date,
        season=season,
        min_pa=min_pa,
        schedule_rows=len(schedule_df),
        bvp_rows=len(bvp_matchups),
        hand_rows=len(hand_matchups),
        k_rows=len(pitcher_k_matchups),
        game_logs_built=game_logs_built
    )

    write_log("Nightly refresh completed successfully")
    write_log("========================================")


def main():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--date",
        default=date.today().strftime("%Y-%m-%d"),
        help="Game date to refresh, format YYYY-MM-DD"
    )

    parser.add_argument(
        "--season",
        default=date.today().year,
        type=int,
        help="MLB season year"
    )

    parser.add_argument(
        "--min-pa",
        default=100,
        type=int,
        help="Minimum season plate appearances to include hitters"
    )

    parser.add_argument(
        "--build-game-logs",
        action="store_true",
        help="Preload career BvP game logs into data/matchup_cache.json"
    )

    parser.add_argument(
        "--max-game-logs",
        default=50,
        type=int,
        help="Maximum number of career BvP game logs to preload"
    )

    args = parser.parse_args()

    try:
        run_nightly_refresh(
            game_date=args.date,
            season=args.season,
            min_pa=args.min_pa,
            build_game_logs=args.build_game_logs,
            max_game_logs=args.max_game_logs
        )

    except Exception as error:
        write_log("ERROR during nightly refresh")
        write_log(str(error))
        write_log(traceback.format_exc())
        raise


if __name__ == "__main__":
    main()