"""Historical Statcast pitch-data backfill for Advanced HVP.

This script is intentionally separate from the Streamlit app so the runtime
does not import or initialize pybaseball during interactive renders.
"""

from __future__ import annotations

import argparse
from datetime import date, datetime, timedelta
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.pitch_data import save_statcast_frame


def parse_args():
    parser = argparse.ArgumentParser(description="Backfill MLB Statcast pitch-level data.")
    parser.add_argument("--start", required=True, help="Start date, YYYY-MM-DD.")
    parser.add_argument("--end", required=True, help="End date, YYYY-MM-DD.")
    parser.add_argument(
        "--chunk-days",
        type=int,
        default=7,
        help="Inclusive date-window size per pybaseball request.",
    )
    return parser.parse_args()


def _date(value):
    return datetime.strptime(value, "%Y-%m-%d").date()


def _load_statcast():
    try:
        from pybaseball import statcast
    except ImportError as exc:
        raise SystemExit(
            "pybaseball is required for pitch-data backfill. "
            "Install refresh-only dependencies before running this script."
        ) from exc
    return statcast


def iter_windows(start_date: date, end_date: date, chunk_days: int):
    current = start_date
    while current <= end_date:
        window_end = min(end_date, current + timedelta(days=max(1, chunk_days) - 1))
        yield current, window_end
        current = window_end + timedelta(days=1)


def main():
    args = parse_args()
    start_date = _date(args.start)
    end_date = _date(args.end)
    if end_date < start_date:
        raise SystemExit("--end must be on or after --start")
    statcast = _load_statcast()
    total_saved = 0
    for window_start, window_end in iter_windows(start_date, end_date, args.chunk_days):
        frame = statcast(
            start_dt=window_start.isoformat(),
            end_dt=window_end.isoformat(),
        )
        total_saved += save_statcast_frame(frame)
        print(f"{window_start} to {window_end}: saved {len(frame)} raw rows")
    print(f"Saved {total_saved} deduplicated pitch events")


if __name__ == "__main__":
    main()
