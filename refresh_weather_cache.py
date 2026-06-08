import argparse
from datetime import date, datetime, timedelta, timezone
import json
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

from src.mlb_schedule import get_daily_schedule
from src.weather import enrich_schedule_with_weather


def json_value(value):
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    if hasattr(value, "item"):
        return value.item()
    return value


def build_weather_cache(start_date, days):
    records = []
    for offset in range(days):
        game_date = start_date + timedelta(days=offset)
        schedule = get_daily_schedule(game_date.isoformat())
        if schedule.empty:
            continue

        weather = enrich_schedule_with_weather(schedule)
        for record in weather.to_dict("records"):
            records.append(
                {
                    key: json_value(value)
                    for key, value in record.items()
                }
            )

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "start_date": start_date.isoformat(),
        "days": days,
        "records": records,
    }


def parse_args():
    parser = argparse.ArgumentParser(
        description="Publish current MLB schedule weather for Streamlit fallback."
    )
    parser.add_argument(
        "--start-date",
        type=date.fromisoformat,
        default=datetime.now(ZoneInfo("America/Denver")).date(),
    )
    parser.add_argument("--days", type=int, default=8)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/weather.json"),
    )
    return parser.parse_args()


def main():
    args = parse_args()
    payload = build_weather_cache(args.start_date, args.days)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, separators=(",", ":")),
        encoding="utf-8",
    )
    available = sum(
        record.get("weather_status") == "Forecast available"
        for record in payload["records"]
    )
    print(
        f"Wrote {len(payload['records'])} games to {args.output} "
        f"({available} with weather)."
    )


if __name__ == "__main__":
    main()
