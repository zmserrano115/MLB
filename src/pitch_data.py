"""Pitch-level data normalization used by refresh/backfill jobs."""

from __future__ import annotations

from collections import defaultdict

import pandas as pd

from src import database
from src.pitch_analysis import (
    calculate_pitch_type_summaries,
    normalize_pitch_code,
    pitch_name_for_code,
    plate_appearance_logs_from_pitches,
    safe_float,
    safe_int,
)


STATCAST_FIELD_MAP = {
    "game_pk": "game_pk",
    "game_date": "game_date",
    "at_bat_number": "at_bat_number",
    "pitch_number": "pitch_number",
    "batter": "batter_id",
    "pitcher": "pitcher_id",
    "stand": "batter_side",
    "p_throws": "pitcher_hand",
    "pitch_type": "pitch_type",
    "release_speed": "release_speed",
    "release_spin_rate": "release_spin_rate",
    "pfx_x": "pfx_x",
    "pfx_z": "pfx_z",
    "plate_x": "plate_x",
    "plate_z": "plate_z",
    "zone": "zone",
    "description": "pitch_description",
    "events": "event",
    "launch_speed": "launch_speed",
    "launch_angle": "launch_angle",
    "hit_distance_sc": "estimated_distance",
    "estimated_woba_using_speedangle": "estimated_woba",
    "estimated_ba_using_speedangle": "estimated_ba",
    "balls": "balls",
    "strikes": "strikes",
    "outs_when_up": "outs",
    "inning": "inning",
    "rbi": "rbi",
}


def statcast_frame_to_pitch_events(frame):
    frame = pd.DataFrame(frame)
    if frame.empty:
        return []
    rows = []
    for _, source in frame.iterrows():
        row = {}
        for source_column, target_column in STATCAST_FIELD_MAP.items():
            row[target_column] = source.get(source_column)
        pitch_code = normalize_pitch_code(row.get("pitch_type"))
        row["pitch_type"] = pitch_code
        row["pitch_name"] = source.get("pitch_name") or pitch_name_for_code(pitch_code)
        launch_speed = safe_float(row.get("launch_speed"))
        row["hard_hit"] = 1 if launch_speed is not None and launch_speed >= 95 else 0
        row["barrel"] = 1 if _is_barrel(source) else 0
        row["runs_produced"] = safe_int(source.get("post_bat_score")) - safe_int(
            source.get("bat_score")
        ) if source.get("post_bat_score") is not None and source.get("bat_score") is not None else None
        rows.append(row)
    return _dedupe_pitch_events(rows)


def _is_barrel(row):
    value = row.get("barrel")
    if value is not None and str(value).strip() != "":
        return bool(safe_int(value))
    launch_speed = safe_float(row.get("launch_speed"))
    launch_angle = safe_float(row.get("launch_angle"))
    if launch_speed is None or launch_angle is None:
        return False
    return launch_speed >= 98 and 26 <= launch_angle <= 30


def _dedupe_pitch_events(rows):
    result = {}
    for row in rows:
        key = (
            safe_int(row.get("game_pk"), default=None),
            safe_int(row.get("at_bat_number"), default=None),
            safe_int(row.get("pitch_number"), default=None),
        )
        if None in key:
            continue
        result[key] = row
    return [
        result[key]
        for key in sorted(result, key=lambda item: (item[0], item[1], item[2]))
    ]


def plate_sequence_rows(events):
    sequence_rows = []
    for pa in plate_appearance_logs_from_pitches(events):
        sequence_rows.append(
            {
                "game_pk": pa.get("game_pk"),
                "game_date": pa.get("game_date"),
                "season": pd.to_datetime(pa.get("game_date"), errors="coerce").year
                if pd.notna(pd.to_datetime(pa.get("game_date"), errors="coerce"))
                else None,
                "at_bat_number": pa.get("at_bat_number"),
                "batter_id": pa.get("batter_id"),
                "pitcher_id": pa.get("pitcher_id"),
                "inning": pa.get("inning"),
                "outs": pa.get("outs"),
                "starting_count": pa.get("starting_count"),
                "final_count": pa.get("final_count"),
                "pa_result": pa.get("event"),
                "rbi": pa.get("rbi"),
                "runs_produced": pa.get("runs_produced"),
                "pitch_count": pa.get("pitch_count"),
                "pitch_sequence": pa.get("pitch_sequence"),
                "launch_speed": pa.get("launch_speed"),
                "launch_angle": pa.get("launch_angle"),
                "estimated_distance": pa.get("estimated_distance"),
                "barrel": pa.get("barrel"),
                "hard_hit": pa.get("hard_hit"),
            }
        )
    return sequence_rows


def bvp_pitch_type_summary_rows(events):
    grouped = defaultdict(list)
    for event in events:
        batter_id = safe_int(event.get("batter_id"), default=None)
        pitcher_id = safe_int(event.get("pitcher_id"), default=None)
        game_date = pd.to_datetime(event.get("game_date"), errors="coerce")
        if batter_id is None or pitcher_id is None or pd.isna(game_date):
            continue
        grouped[(game_date.year, batter_id, pitcher_id)].append(event)

    rows = []
    for (season, batter_id, pitcher_id), pitch_rows in grouped.items():
        last_game_date = max(
            str(row.get("game_date"))
            for row in pitch_rows
            if row.get("game_date") is not None
        )
        for summary in calculate_pitch_type_summaries(pitch_rows):
            rows.append(
                {
                    "season": season,
                    "batter_id": batter_id,
                    "pitcher_id": pitcher_id,
                    "pitch_type": summary.get("pitch_type"),
                    "pitch_name": summary.get("pitch_name"),
                    "pitch_count": summary.get("pitch_count"),
                    "usage_pct": summary.get("usage_pct"),
                    "avg_velocity": summary.get("avg_velocity"),
                    "max_velocity": summary.get("max_velocity"),
                    "avg_spin_rate": summary.get("avg_spin_rate"),
                    "horizontal_movement": summary.get("horizontal_movement"),
                    "vertical_movement": summary.get("vertical_movement"),
                    "zone_pct": summary.get("zone_pct"),
                    "chase_pct": summary.get("chase_pct"),
                    "whiff_pct": summary.get("whiff_pct"),
                    "csw_pct": summary.get("csw_pct"),
                    "contact_pct": summary.get("contact_pct"),
                    "hard_hit_pct": summary.get("hard_hit_pct"),
                    "barrel_pct": summary.get("barrel_pct"),
                    "AVG": summary.get("AVG"),
                    "SLG": summary.get("SLG"),
                    "wOBA": summary.get("wOBA"),
                    "xwOBA": summary.get("xwOBA"),
                    "K_pct": summary.get("K%"),
                    "balls_in_play": summary.get("balls_in_play"),
                    "sample_size": summary.get("sample_size"),
                    "last_game_date": last_game_date,
                }
            )
    return rows


def save_pitch_events(events):
    events = list(events or [])
    pitch_count = database.save_pitch_level_events(events)
    database.save_plate_appearance_sequences(plate_sequence_rows(events))
    database.save_bvp_pitch_type_stats(bvp_pitch_type_summary_rows(events))
    return pitch_count


def save_statcast_frame(frame):
    events = statcast_frame_to_pitch_events(frame)
    return save_pitch_events(events)
