from __future__ import annotations

from typing import Any

from pydantic import Field

from all_rise_api.schemas.common import StrictModel


class LiveGameData(StrictModel):
    game_id: str
    version: str
    observed_at: str
    feed_timestamp: str | None = None
    abstract_state: str
    detailed_state: str
    is_final: bool
    inning: int = 0
    inning_ordinal: str | None = None
    half_inning: str | None = None
    count: dict[str, int | None]
    teams: dict[str, dict[str, Any]]
    bases: dict[str, bool]
    matchup: dict[str, Any]
    pitches: list[dict[str, Any]] = Field(max_length=12)
    recent_plays: list[dict[str, Any]] = Field(max_length=8)
    boxscore: dict[str, Any]
    payload_size_bytes: int = Field(gt=0, le=131_072)
