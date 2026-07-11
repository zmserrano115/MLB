"""Incremental rolling pitch-data refresh for Advanced HVP."""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src import database
from src.pitch_data import save_statcast_frame
from src.time_utils import current_app_date


def parse_args():
    parser = argparse.ArgumentParser(description="Refresh recent Statcast pitch rows.")
    parser.add_argument(
        "--through",
        default=None,
        help="End date, YYYY-MM-DD. Defaults to the app's current date.",
    )
    parser.add_argument(
        "--recheck-days",
        type=int,
        default=4,
        help="Rolling correction window, including the through date.",
    )
    return parser.parse_args()


def _load_statcast():
    try:
        from pybaseball import statcast
    except ImportError as exc:
        raise SystemExit(
            "pybaseball is required for pitch-data refresh. "
            "Install refresh-only dependencies before running this script."
        ) from exc
    return statcast


def refresh_pitch_data_window(through_date=None, recheck_days=4):
    through_date = through_date or current_app_date()
    if isinstance(through_date, str):
        through_date = datetime.strptime(through_date, "%Y-%m-%d").date()
    start_date = through_date - timedelta(days=max(1, recheck_days) - 1)
    statcast = _load_statcast()
    try:
        frame = statcast(
            start_dt=start_date.isoformat(),
            end_dt=through_date.isoformat(),
        )
        saved = save_statcast_frame(frame)
        database.log_refresh(
            refresh_type="pitch_data",
            refresh_date=through_date.isoformat(),
            games_checked=0,
            games_processed=0,
            plate_appearances_loaded=saved,
            pitcher_logs_loaded=0,
            status="success",
            message=f"Refreshed Statcast pitch rows from {start_date} to {through_date}",
        )
        print(f"Saved {saved} deduplicated pitch events")
        return saved
    except Exception as exc:
        database.log_refresh(
            refresh_type="pitch_data",
            refresh_date=through_date.isoformat(),
            games_checked=0,
            games_processed=0,
            plate_appearances_loaded=0,
            pitcher_logs_loaded=0,
            status="failed",
            message=str(exc),
        )
        raise


def main():
    args = parse_args()
    through_date = (
        datetime.strptime(args.through, "%Y-%m-%d").date()
        if args.through
        else current_app_date()
    )
    refresh_pitch_data_window(
        through_date=through_date,
        recheck_days=args.recheck_days,
    )


if __name__ == "__main__":
    main()
