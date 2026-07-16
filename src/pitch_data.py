"""Pitch-level data normalization used by refresh/backfill jobs."""

from __future__ import annotations

from collections import defaultdict

import pandas as pd

from src import database
from src.api_client import get_json
from src.pitch_analysis import (
    calculate_pitch_type_summaries,
    normalize_pitch_code,
    pitch_name_for_code,
    plate_appearance_logs_from_pitches,
    safe_float,
    safe_int,
)

MLB_GAME_FEED_URL = "https://statsapi.mlb.com/api/v1.1/game/{game_pk}/feed/live"


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
        scores_available = (
            source.get("post_bat_score") is not None
            and source.get("bat_score") is not None
        )
        row["runs_produced"] = (
            safe_int(source.get("post_bat_score")) - safe_int(source.get("bat_score"))
            if scores_available
            else None
        )
        rows.append(row)
    return _dedupe_pitch_events(rows)


def statsapi_feed_to_matchup_pitch_events(payload, batter_id, pitcher_id):
    """Normalize pitches for one exact batter/pitcher pair from an MLB game feed."""
    payload = payload or {}
    game_pk = safe_int(payload.get("gamePk"), default=None)
    game_date = (payload.get("gameData") or {}).get("datetime", {}).get("officialDate")
    season = safe_int(str(game_date or "")[:4], default=None)
    rows = []
    plays = ((payload.get("liveData") or {}).get("plays") or {}).get("allPlays") or []
    for play in plays:
        matchup = play.get("matchup") or {}
        if (
            safe_int((matchup.get("batter") or {}).get("id"), default=None)
            != int(batter_id)
            or safe_int((matchup.get("pitcher") or {}).get("id"), default=None)
            != int(pitcher_id)
        ):
            continue
        pitch_events = [event for event in play.get("playEvents") or [] if event.get("isPitch")]
        if not pitch_events:
            continue
        final_pitch = pitch_events[-1]
        result = play.get("result") or {}
        about = play.get("about") or {}
        runners = play.get("runners") or []
        runs_scored = sum(
            1
            for runner in runners
            if (runner.get("details") or {}).get("isScoringEvent")
        )
        for offset, event in enumerate(pitch_events, start=1):
            details = event.get("details") or {}
            pitch_data = event.get("pitchData") or {}
            coordinates = pitch_data.get("coordinates") or {}
            breaks = pitch_data.get("breaks") or {}
            hit_data = event.get("hitData") or {}
            pitch_type = details.get("type") or {}
            count = event.get("count") or {}
            description = str(details.get("description") or "").strip().lower()
            description = description.replace(" ", "_").replace("-", "_")
            is_final = event is final_pitch
            launch_speed = safe_float(hit_data.get("launchSpeed"))
            launch_angle = safe_float(hit_data.get("launchAngle"))
            row = {
                "game_pk": game_pk,
                "game_date": game_date,
                "season": season,
                "at_bat_number": safe_int(about.get("atBatIndex"), default=0) + 1,
                "pitch_number": safe_int(event.get("pitchNumber"), default=offset),
                "batter_id": int(batter_id),
                "pitcher_id": int(pitcher_id),
                "batter_side": (matchup.get("batSide") or {}).get("code"),
                "pitcher_hand": (matchup.get("pitchHand") or {}).get("code"),
                "pitch_type": normalize_pitch_code(pitch_type.get("code")),
                "pitch_name": pitch_type.get("description"),
                "release_speed": safe_float(pitch_data.get("startSpeed")),
                "release_spin_rate": safe_float(breaks.get("spinRate")),
                "pfx_x": safe_float(coordinates.get("pfxX")),
                "pfx_z": safe_float(coordinates.get("pfxZ")),
                "plate_x": safe_float(coordinates.get("pX")),
                "plate_z": safe_float(coordinates.get("pZ")),
                "zone": safe_int(pitch_data.get("zone"), default=None),
                "pitch_description": description,
                "event": result.get("eventType") if is_final else None,
                "launch_speed": launch_speed,
                "launch_angle": launch_angle,
                "estimated_distance": safe_float(hit_data.get("totalDistance")),
                "estimated_woba": None,
                "estimated_ba": None,
                "barrel": (
                    1
                    if _is_barrel(
                        {"launch_speed": launch_speed, "launch_angle": launch_angle}
                    )
                    else 0
                ),
                "hard_hit": 1 if launch_speed is not None and launch_speed >= 95 else 0,
                "balls": safe_int(count.get("balls"), default=None),
                "strikes": safe_int(count.get("strikes"), default=None),
                "outs": safe_int(count.get("outs"), default=None),
                "inning": safe_int(about.get("inning"), default=None),
                "rbi": safe_int(result.get("rbi"), default=0) if is_final else None,
                "runs_produced": runs_scored if is_final else None,
            }
            rows.append(row)
    return _dedupe_pitch_events(rows)


def fetch_matchup_pitch_events(batter_id, pitcher_id, game_logs, feed_loader=None):
    """Load only game feeds known to contain the selected matchup."""
    loader = feed_loader or (
        lambda game_pk: get_json(
            MLB_GAME_FEED_URL.format(game_pk=int(game_pk)),
            provider="MLB StatsAPI",
            timeout=20,
        )
    )
    game_pks = []
    for log in game_logs or []:
        game_pk = safe_int(log.get("game_pk"), default=None)
        if game_pk is not None and game_pk not in game_pks:
            game_pks.append(game_pk)
    rows = []
    for game_pk in game_pks:
        try:
            payload = loader(game_pk)
        except Exception:
            continue
        rows.extend(
            statsapi_feed_to_matchup_pitch_events(payload, batter_id, pitcher_id)
        )
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
