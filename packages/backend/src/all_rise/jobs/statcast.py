from __future__ import annotations

from collections.abc import Iterable, Iterator, Mapping
from datetime import date, datetime, timedelta
from typing import Any

Event = Mapping[str, Any]
EVENT_KEY_FIELDS = ("game_pk", "at_bat_number", "pitch_number")


def inclusive_windows(start: date, end: date, *, chunk_days: int) -> Iterator[tuple[date, date]]:
    """Yield complete, non-overlapping inclusive windows without boundary gaps."""
    if end < start:
        raise ValueError("end must be on or after start")
    if chunk_days <= 0:
        raise ValueError("chunk_days must be positive")
    current = start
    while current <= end:
        window_end = min(end, current + timedelta(days=chunk_days - 1))
        yield current, window_end
        current = window_end + timedelta(days=1)


def correction_window(through: date, *, recheck_days: int) -> tuple[date, date]:
    if recheck_days <= 0:
        raise ValueError("recheck_days must be positive")
    return through - timedelta(days=recheck_days - 1), through


def event_key(event: Event) -> tuple[int, int, int]:
    try:
        return tuple(int(event[field]) for field in EVENT_KEY_FIELDS)  # type: ignore[return-value]
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("Statcast event lacks a stable pitch identity") from exc


def _observed_at(event: Event) -> datetime:
    raw = event.get("source_updated_at") or event.get("fetched_at")
    if isinstance(raw, datetime):
        return raw
    if isinstance(raw, str):
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    return datetime.min


def merge_corrections(
    existing: Iterable[Event],
    fetched_windows: Iterable[Iterable[Event]],
) -> list[dict[str, Any]]:
    """Apply late Statcast corrections deterministically, independent of window size."""
    merged: dict[tuple[int, int, int], dict[str, Any]] = {}
    for event in [*existing, *(event for window in fetched_windows for event in window)]:
        key = event_key(event)
        current = merged.get(key)
        if current is None or _observed_at(event) >= _observed_at(current):
            merged[key] = dict(event)
    return [merged[key] for key in sorted(merged)]
