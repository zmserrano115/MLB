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


class PitchCoverageData(StrictModel):
    pitch_count: int
    games: int
    last_game_date: date | None = None


class PitchTypeData(StrictModel):
    season: int
    pitch_type: str
    pitch_name: str | None = None
    pitch_count: int
    average_velocity: float | None = None
    whiff_percentage: float | None = None
    hard_hit_percentage: float | None = None
    barrel_percentage: float | None = None
    expected_woba: float | None = None
    last_game_date: date | None = None


class PitchSequenceData(StrictModel):
    game_id: str
    game_date: date
    at_bat_number: int
    result: str | None = None
    pitch_count: int
    pitch_sequence: str
    launch_speed: float | None = None
    launch_angle: float | None = None
    estimated_distance: float | None = None
    barrel: bool | None = None
    hard_hit: bool | None = None


class AdvancedMatchupData(StrictModel):
    coverage: PitchCoverageData
    pitch_types: list[PitchTypeData]
    sequences: list[PitchSequenceData]


class PitcherOpponentSplitData(StrictModel):
    pitcher_id: int
    pitcher_name: str | None = None
    opponent: str | None = None
    games: int
    innings_outs: int
    batters_faced: int
    strikeouts: int
    walks: int
    hits: int
    home_runs: int
    runs: int
    earned_runs: int
    last_game_date: date | None = None


class PitcherOpponentLogData(StrictModel):
    game_id: str
    game_date: date
    season: int
    opponent: str | None = None
    is_starter: bool
    innings_outs: int
    pitch_count: int | None = None
    batters_faced: int
    hits: int
    walks: int
    strikeouts: int
    home_runs: int
    runs: int
    earned_runs: int


class PitcherOpponentData(StrictModel):
    splits: list[PitcherOpponentSplitData]
    game_logs: list[PitcherOpponentLogData]


class BullpenProjectionData(StrictModel):
    game_id: str
    team: str | None = None
    pitcher_id: int
    pitcher_name: str | None = None
    projected_role: str | None = None
    availability_score: float | None = None
    availability_label: str | None = None
    appearance_probability: float | None = None
    expected_batters_faced_min: int | None = None
    expected_batters_faced_max: int | None = None
    recent_workload: str | None = None
    reason: str | None = None
    generation: str
    batter_pa: int | None = None
    batter_hits: int | None = None
    batter_home_runs: int | None = None
    batter_strikeouts: int | None = None


class StreakData(StrictModel):
    through_date: date
    group: str
    metric: str
    subject_id: str | None = None
    subject_name: str | None = None
    team: str | None = None
    streak: int
    last_game_date: date | None = None


class PlayerLeaderboardData(StrictModel):
    season: int
    player_id: int
    name: str | None = None
    team: str | None = None
    games: int
    starts: int | None = None
    pa: int | None = None
    ab: int | None = None
    innings_outs: int | None = None
    hits: int | None = None
    home_runs: int | None = None
    rbi: int | None = None
    walks: int
    strikeouts: int
    total_bases: int | None = None
    average: float | None = None
    ops: float | None = None
    era: float | None = None
    whip: float | None = None
    last_game_date: date | None = None


class TeamLeaderboardData(StrictModel):
    season: int
    team_id: int | None = None
    name: str
    abbreviation: str | None = None
    games: int
    pa: int
    runs: int
    hits: int
    walks: int
    strikeouts: int
    home_runs: int
    innings_outs: int
    runs_allowed: int
    earned_runs_allowed: int
    hits_allowed: int
    walks_allowed: int
    strikeouts_pitched: int
    home_runs_allowed: int
    average: float | None = None
    era: float | None = None
    last_game_date: date | None = None
