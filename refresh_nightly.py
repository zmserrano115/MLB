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
        pd_text = ""
        file_path.write_text(pd_text, encoding="utf-8")
        return

    df.to_csv(file_path, index=False)


def save_metadata(game_date, season, min_pa, schedule_rows, bvp_rows, hand_rows, k_rows):
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
        "pitcher_k_rows": k_rows
    }

    metadata_path = PRECOMPUTED_DIR / "latest_metadata.json"

    with open(metadata_path, "w", encoding="utf-8") as file:
        json.dump(metadata, file, indent=4)


def run_nightly_refresh(game_date, season, min_pa=100, rebuild_game_logs=False):
    """
    Refreshes MLB matchup data.

    This script is meant to be run by GitHub Actions every morning.
    """

    write_log("========================================")
    write_log("Starting nightly MLB data refresh")
    write_log(f"Game date: {game_date}")
    write_log(f"Season: {season}")
    write_log(f"Minimum PA: {min_pa}")

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
            k_rows=0
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
        k_rows=len(pitcher_k_matchups)
    )

    if rebuild_game_logs and not bvp_matchups.empty:
        write_log("Rebuilding career BvP game logs for matchups with history...")

        bvp_with_history = bvp_matchups[
            bvp_matchups["PA"] > 0
        ].copy()

        write_log(f"Game logs to check: {len(bvp_with_history)}")

        for _, row in bvp_with_history.iterrows():
            batter = row.get("batter")
            pitcher = row.get("opposing_pitcher")
            batter_id = row.get("batter_id")
            pitcher_id = row.get("opposing_pitcher_id")

            if batter_id is None or pitcher_id is None:
                continue

            write_log(f"Building game log: {batter} vs {pitcher}")

            get_batter_vs_pitcher_game_log(
                batter_id=int(batter_id),
                pitcher_id=int(pitcher_id),
                season=season
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
        "--rebuild-game-logs",
        action="store_true",
        help="Also rebuild career BvP game logs for matchups with history"
    )

    args = parser.parse_args()

    try:
        run_nightly_refresh(
            game_date=args.date,
            season=args.season,
            min_pa=args.min_pa,
            rebuild_game_logs=args.rebuild_game_logs
        )

    except Exception as error:
        write_log("ERROR during nightly refresh")
        write_log(str(error))
        write_log(traceback.format_exc())
        raise


if __name__ == "__main__":
    main()