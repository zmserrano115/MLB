"""Pure recent-game series calculations."""

from __future__ import annotations

import pandas as pd


def recent_game_values(
    game_log_df: pd.DataFrame | None,
    value_column: str,
    limit: int = 5,
) -> list[dict[str, str | float]]:
    if game_log_df is None or game_log_df.empty or value_column not in game_log_df:
        return []
    columns = ["game_date", value_column]
    if "home_away" in game_log_df.columns:
        columns.append("home_away")
    recent = game_log_df[columns].copy()
    recent["parsed_date"] = pd.to_datetime(recent["game_date"], errors="coerce")
    recent["value"] = pd.to_numeric(recent[value_column], errors="coerce").fillna(0)
    recent = recent.sort_values("parsed_date", ascending=False).head(limit)
    recent = recent.sort_values("parsed_date")
    values: list[dict[str, str | float]] = []
    for _, row in recent.iterrows():
        parsed_date = row["parsed_date"]
        label = (
            f"{parsed_date.month}/{parsed_date.day}"
            if pd.notna(parsed_date)
            else str(row["game_date"])
        )
        home_away = str(row.get("home_away") or "").strip().lower()
        if home_away in {"home", "away"}:
            label = f"{label} ({home_away[0].upper()})"
        values.append({"date": label, "value": float(row["value"])})
    return values
