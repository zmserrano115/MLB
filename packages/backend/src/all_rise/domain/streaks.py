"""Pure historical and live streak calculations."""

from __future__ import annotations

from datetime import date

import pandas as pd


def is_final_state(game_state: object, detailed_state: object | None = None) -> bool:
    values = {str(game_state or "").lower(), str(detailed_state or "").lower()}
    return "final" in values or any("final" in value for value in values)


def count_historical_streak(
    game_log_df: pd.DataFrame | None,
    stat_column: str,
    threshold: float,
    skip_date: object | None = None,
) -> int:
    if game_log_df is None or game_log_df.empty or stat_column not in game_log_df:
        return 0
    logs = game_log_df.copy()
    logs["parsed_date"] = pd.to_datetime(logs["game_date"], errors="coerce")
    logs = logs.dropna(subset=["parsed_date"])
    if skip_date is not None:
        parsed_skip_date = pd.to_datetime(skip_date).date()
        logs = logs[logs["parsed_date"].dt.date != parsed_skip_date]
    logs = logs.sort_values("parsed_date", ascending=False)
    streak = 0
    for _, row in logs.iterrows():
        value = pd.to_numeric(row.get(stat_column), errors="coerce")
        if pd.notna(value) and float(value) >= threshold:
            streak += 1
            continue
        break
    return streak


def calculate_live_streak(
    game_log_df: pd.DataFrame | None,
    stat_column: str,
    threshold: float,
    current_value: object | None = None,
    current_game_state: object | None = None,
    detailed_state: object | None = None,
    selected_date: object | None = None,
    live_played: bool = False,
) -> dict[str, object]:
    numeric_current = pd.to_numeric(current_value, errors="coerce")
    has_current_value = pd.notna(numeric_current)
    skip_date = selected_date if has_current_value or live_played else None
    base_streak = count_historical_streak(game_log_df, stat_column, threshold, skip_date=skip_date)
    if has_current_value and float(numeric_current) >= threshold:
        return {
            "streak": base_streak + 1,
            "today_value": float(numeric_current),
            "status": (
                "Final +1" if is_final_state(current_game_state, detailed_state) else "Live +1"
            ),
        }
    if live_played and is_final_state(current_game_state, detailed_state):
        return {
            "streak": 0,
            "today_value": float(numeric_current) if has_current_value else 0,
            "status": "Ended",
        }
    if live_played:
        return {
            "streak": base_streak,
            "today_value": float(numeric_current) if has_current_value else 0,
            "status": "In progress",
        }
    status = "Pre-game" if isinstance(selected_date, date) else "Pending"
    return {
        "streak": base_streak,
        "today_value": float(numeric_current) if has_current_value else None,
        "status": status,
    }
