from __future__ import annotations

from datetime import date

from all_rise_api.schemas.common import StrictModel


class PlayerData(StrictModel):
    player_id: str
    name: str | None = None
    active_status: str
    player_type: str
    latest_season: int | None = None
    last_game_date: date | None = None


class BattingSummaryData(StrictModel):
    season: int
    games: int
    pa: int
    ab: int
    hits: int
    doubles: int
    triples: int
    walks: int
    hit_by_pitch: int
    strikeouts: int
    home_runs: int
    rbi: int
    total_bases: int
    batting_average: float | None = None
    on_base_percentage: float | None = None
    slugging_percentage: float | None = None


class PitchingSummaryData(StrictModel):
    season: int
    games: int
    starts: int
    innings_outs: int
    pitch_count: int
    batters_faced: int
    hits: int
    walks: int
    hit_by_pitch: int
    strikeouts: int
    home_runs: int
    runs: int
    earned_runs: int
    earned_run_average: float | None = None
    whip: float | None = None


class PlayerGameLogData(StrictModel):
    game_id: str
    game_date: date
    season: int
    group: str
    opponent: str | None = None
    games: int = 1
    pa: int | None = None
    ab: int | None = None
    hits: int | None = None
    walks: int | None = None
    strikeouts: int | None = None
    home_runs: int | None = None
    rbi: int | None = None
    total_bases: int | None = None
    is_starter: bool | None = None
    innings_outs: int | None = None
    pitch_count: int | None = None
    batters_faced: int | None = None
    runs: int | None = None
    earned_runs: int | None = None


class PlayerProfileData(StrictModel):
    player: PlayerData
    batting: BattingSummaryData | None = None
    pitching: PitchingSummaryData | None = None
    game_logs: list[PlayerGameLogData]
    selected_group: str


class BatterPitcherMatchupData(StrictModel):
    batter_id: str
    batter_name: str | None = None
    pitcher_id: str
    pitcher_name: str | None = None
    season: int | None = None
    games: int
    pa: int
    ab: int
    hits: int
    doubles: int
    triples: int
    walks: int
    hit_by_pitch: int
    strikeouts: int
    home_runs: int
    rbi: int
    total_bases: int
    batting_average: float | None = None
    on_base_percentage: float | None = None
    slugging_percentage: float | None = None
    last_game_date: date | None = None
    game_logs: list[PlayerGameLogData]
