import argparse
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
import traceback

from refresh_database import refresh_completed_games
from src import database


def refresh_dates(end_date, lookback_days):
    end = datetime.strptime(end_date, "%Y-%m-%d").date()
    start = end - timedelta(days=max(lookback_days, 1) - 1)
    current = start
    while current <= end:
        yield current.strftime("%Y-%m-%d")
        current += timedelta(days=1)


def run_nightly_refresh(
    end_date,
    lookback_days=3,
    game_type="R",
    reprocess_existing=False,
):
    """Update only final-game BvP history and pitcher logs."""
    database.init_database()
    totals = defaultdict(int)
    dates = list(refresh_dates(end_date, lookback_days))

    print("========================================")
    print("Starting nightly completed-game refresh")
    print(f"Dates: {dates[0]} through {dates[-1]}")
    print("========================================")

    for refresh_date in dates:
        result = refresh_completed_games(
            refresh_date=refresh_date,
            game_type=game_type,
            reprocess_existing=reprocess_existing,
            rebuild_after=False,
            write_refresh_log=False,
        )
        for key, value in result.items():
            totals[key] += value

    print("Rebuilding aggregate matchup and pitcher season summaries...")
    database.rebuild_all_summary_stats()

    status = "success" if totals["errors"] == 0 else "completed_with_errors"
    message = (
        f"Dates checked: {len(dates)}. "
        f"Games checked: {totals['games_checked']}. "
        f"Games processed: {totals['games_processed']}. "
        f"Plate appearances loaded: {totals['plate_appearances_loaded']}. "
        f"Pitcher logs loaded: {totals['pitcher_logs_loaded']}. "
        f"Errors: {totals['errors']}."
    )
    database.log_refresh(
        refresh_type="nightly_completed_games",
        refresh_date=f"{dates[0]}_to_{dates[-1]}",
        games_checked=totals["games_checked"],
        games_processed=totals["games_processed"],
        plate_appearances_loaded=totals["plate_appearances_loaded"],
        pitcher_logs_loaded=totals["pitcher_logs_loaded"],
        status=status,
        message=message,
    )

    print(message)
    database.print_database_counts()
    return dict(totals)


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Refresh final MLB games from StatsAPI. This job does not build "
            "future schedules or precomputed matchup CSV files."
        )
    )
    parser.add_argument(
        "--date",
        default=(date.today() - timedelta(days=1)).strftime("%Y-%m-%d"),
        help="Last completed-game date to check. Defaults to yesterday.",
    )
    parser.add_argument(
        "--lookback-days",
        type=int,
        default=3,
        help="Number of dates ending at --date to recheck for late finals.",
    )
    parser.add_argument("--game-type", default="R")
    parser.add_argument("--reprocess-existing", action="store_true")
    parser.add_argument("--db", help="Optional SQLite path.")
    args = parser.parse_args()

    if args.db:
        database.DB_PATH = Path(args.db).expanduser().resolve()

    try:
        run_nightly_refresh(
            end_date=args.date,
            lookback_days=args.lookback_days,
            game_type=args.game_type,
            reprocess_existing=args.reprocess_existing,
        )
    except Exception as error:
        try:
            database.log_refresh(
                refresh_type="nightly_completed_games",
                refresh_date=args.date,
                games_checked=0,
                games_processed=0,
                plate_appearances_loaded=0,
                pitcher_logs_loaded=0,
                status="error",
                message=str(error),
            )
        except Exception:
            pass
        print("ERROR during nightly completed-game refresh")
        traceback.print_exc()
        raise


if __name__ == "__main__":
    main()
