"""Pure normalization helpers for MLB live-feed payloads."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pandas as pd

PLAY_RESULT_LABELS = {
    "strikeout": "Strikeout",
    "groundout": "Groundout",
    "flyout": "Flyout",
    "popout": "Popout",
    "lineout": "Lineout",
    "forceout": "Forceout",
    "double_play": "Double Play",
    "single": "Single",
    "double": "Double",
    "triple": "Triple",
    "home_run": "Home Run",
    "walk": "Walk",
    "hit_by_pitch": "Hit By Pitch",
    "error": "Error",
    "sac_fly": "Sac Fly",
    "stolen_base": "Stolen Base",
    "other": "Other",
}


def safe_int(value: object, default: int | None = 0) -> int | None:
    number = pd.to_numeric(value, errors="coerce")
    if pd.isna(number):
        return default
    return int(number)


def safe_float(value: object, default: float | None = None) -> float | None:
    number = pd.to_numeric(value, errors="coerce")
    if pd.isna(number):
        return default
    return float(number)


def classify_play_result(result: Mapping[str, object] | None) -> str:
    result = result or {}
    event = str(result.get("event") or "").strip().lower()
    event_type = str(result.get("eventType") or "").strip().lower()
    combined = f"{event} {event_type}".replace("_", " ")
    rules = (
        ("home_run", ("home run", "homer")),
        ("hit_by_pitch", ("hit by pitch",)),
        ("stolen_base", ("stolen base",)),
        ("sac_fly", ("sac fly", "sacrifice fly")),
        ("double_play", ("double play", "grounded into dp")),
        ("strikeout", ("strikeout", "strike out")),
        ("forceout", ("forceout", "force out")),
        ("groundout", ("groundout", "ground out")),
        ("flyout", ("flyout", "fly out")),
        ("popout", ("popout", "pop out")),
        ("lineout", ("lineout", "line out")),
        ("triple", ("triple",)),
        ("double", ("double",)),
        ("single", ("single",)),
        ("walk", ("intent walk", "intentional walk", "walk")),
        ("error", ("error", "field error")),
    )
    for result_type, terms in rules:
        if any(term in combined for term in terms):
            return result_type
    return "other"


def _pitch_count(event: Mapping[str, Any] | None) -> dict[str, int | None]:
    count = (event or {}).get("count") or {}
    return {
        "balls": safe_int(count.get("balls")),
        "strikes": safe_int(count.get("strikes")),
        "outs": safe_int(count.get("outs")),
    }


def parse_pitch_event(event: Mapping[str, Any] | None) -> dict[str, object]:
    event = event or {}
    details = event.get("details") or {}
    pitch_data = event.get("pitchData") or {}
    coordinates = pitch_data.get("coordinates") or {}
    pitch_type = details.get("type") or {}
    call = details.get("call") or {}
    return {
        "play_id": event.get("playId"),
        "event_index": event.get("index"),
        "description": details.get("description") or call.get("description") or "",
        "code": details.get("code") or call.get("code"),
        "call": call.get("description") or details.get("description") or "",
        "is_strike": bool(details.get("isStrike")),
        "is_ball": bool(details.get("isBall")),
        "is_in_play": bool(details.get("isInPlay")),
        "is_out": bool(details.get("isOut")),
        "count_after": _pitch_count(event),
        "zone": safe_int(details.get("zone"), default=None),
        "pitch_type": pitch_type.get("description") or pitch_type.get("code"),
        "pitch_code": pitch_type.get("code"),
        "start_speed": safe_float(pitch_data.get("startSpeed")),
        "p_x": safe_float(coordinates.get("pX")),
        "p_z": safe_float(coordinates.get("pZ")),
        "strike_zone_top": safe_float(pitch_data.get("strikeZoneTop")),
        "strike_zone_bottom": safe_float(pitch_data.get("strikeZoneBottom")),
    }


def annotate_pitch_counts(
    pitch_events: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    previous_count: dict[str, int | None] | None = None
    for pitch in pitch_events:
        count_after = _pitch_count({"count": pitch.get("count_after")})
        count_before = (
            dict(previous_count)
            if previous_count is not None
            else {"balls": 0, "strikes": 0, "outs": count_after["outs"]}
        )
        pitch["count_before"] = count_before
        pitch["count_after"] = count_after
        previous_count = count_after
    return pitch_events


def count_current_play_fouls(current_play: Mapping[str, Any]) -> int:
    return sum(
        1
        for event in (current_play.get("playEvents") or [])
        if event.get("isPitch")
        and "foul"
        in " ".join(
            [
                str((event.get("details") or {}).get("description") or ""),
                str(((event.get("details") or {}).get("call") or {}).get("description") or ""),
            ]
        ).lower()
    )
