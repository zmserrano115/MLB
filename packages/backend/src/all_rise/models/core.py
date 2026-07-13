from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from all_rise.models.base import Base

JSON_TYPE = JSON().with_variant(JSONB(), "postgresql")


class Team(Base):
    __tablename__ = "teams"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    source_key: Mapped[str] = mapped_column(String(160), unique=True)
    abbreviation: Mapped[str | None] = mapped_column(String(16), unique=True)
    provider_team_id: Mapped[int | None] = mapped_column(BigInteger, unique=True)
    name: Mapped[str] = mapped_column(String(160))
    source_version: Mapped[str] = mapped_column(String(64))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Player(Base):
    __tablename__ = "players"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    provider_player_id: Mapped[int] = mapped_column(BigInteger, unique=True)
    retrosheet_player_id: Mapped[str | None] = mapped_column(String(32), unique=True)
    name: Mapped[str | None] = mapped_column(String(200))
    active_status: Mapped[str] = mapped_column(String(32), default="unknown")
    source_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Game(Base):
    __tablename__ = "games"
    __table_args__ = (
        CheckConstraint("source_game_id LIKE '%:%'", name="ck_games_canonical_id"),
        CheckConstraint("season BETWEEN 1800 AND 2200", name="ck_games_season"),
        Index("ix_games_game_date", "game_date"),
        Index("ix_games_home_date", "home_team_id", "game_date"),
        Index("ix_games_away_date", "away_team_id", "game_date"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    source_game_id: Mapped[str] = mapped_column(String(80), unique=True)
    mlb_game_pk: Mapped[int | None] = mapped_column(BigInteger, unique=True)
    retrosheet_game_id: Mapped[str | None] = mapped_column(String(32), unique=True)
    legacy_game_pk: Mapped[int] = mapped_column(BigInteger, unique=True)
    source: Mapped[str] = mapped_column(String(32))
    source_version: Mapped[str] = mapped_column(String(64))
    game_date: Mapped[date] = mapped_column(Date)
    season: Mapped[int] = mapped_column(Integer)
    away_team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"))
    home_team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"))
    away_probable_pitcher_id: Mapped[int | None] = mapped_column(ForeignKey("players.id"))
    home_probable_pitcher_id: Mapped[int | None] = mapped_column(ForeignKey("players.id"))
    game_status: Mapped[str | None] = mapped_column(String(64))
    source_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class BatterPitcherGameLog(Base):
    __tablename__ = "batter_pitcher_game_logs"
    __table_args__ = (
        UniqueConstraint("game_id", "batter_id", "pitcher_id", name="uq_bvp_game_batter_pitcher"),
        CheckConstraint("pa >= 0 AND ab >= 0 AND hits >= 0", name="ck_bvp_nonnegative"),
        Index("ix_bvp_batter_pitcher_date", "batter_id", "pitcher_id", "game_date"),
        Index("ix_bvp_season_batter_date", "season", "batter_id", "game_date"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    game_id: Mapped[int] = mapped_column(ForeignKey("games.id"))
    game_date: Mapped[date] = mapped_column(Date)
    season: Mapped[int] = mapped_column(Integer)
    batter_id: Mapped[int] = mapped_column(ForeignKey("players.id"))
    pitcher_id: Mapped[int] = mapped_column(ForeignKey("players.id"))
    batting_team_id: Mapped[int | None] = mapped_column(ForeignKey("teams.id"))
    pitching_team_id: Mapped[int | None] = mapped_column(ForeignKey("teams.id"))
    source: Mapped[str] = mapped_column(String(32))
    pa: Mapped[int] = mapped_column(Integer)
    ab: Mapped[int] = mapped_column(Integer)
    hits: Mapped[int] = mapped_column(Integer)
    doubles: Mapped[int] = mapped_column(Integer)
    triples: Mapped[int] = mapped_column(Integer)
    walks: Mapped[int] = mapped_column(Integer)
    hit_by_pitch: Mapped[int] = mapped_column(Integer)
    strikeouts: Mapped[int] = mapped_column(Integer)
    home_runs: Mapped[int] = mapped_column(Integer)
    rbi: Mapped[int] = mapped_column(Integer)
    sacrifice_flies: Mapped[int] = mapped_column(Integer)
    total_bases: Mapped[int] = mapped_column(Integer)


class BatterPitcherSummary(Base):
    __tablename__ = "batter_pitcher_summaries"

    batter_id: Mapped[int] = mapped_column(ForeignKey("players.id"), primary_key=True)
    pitcher_id: Mapped[int] = mapped_column(ForeignKey("players.id"), primary_key=True)
    pa: Mapped[int] = mapped_column(BigInteger)
    ab: Mapped[int] = mapped_column(BigInteger)
    hits: Mapped[int] = mapped_column(BigInteger)
    doubles: Mapped[int] = mapped_column(BigInteger)
    triples: Mapped[int] = mapped_column(BigInteger)
    walks: Mapped[int] = mapped_column(BigInteger)
    hit_by_pitch: Mapped[int] = mapped_column(BigInteger)
    strikeouts: Mapped[int] = mapped_column(BigInteger)
    home_runs: Mapped[int] = mapped_column(BigInteger)
    rbi: Mapped[int] = mapped_column(BigInteger)
    sacrifice_flies: Mapped[int] = mapped_column(BigInteger)
    total_bases: Mapped[int] = mapped_column(BigInteger)
    batting_average: Mapped[Decimal | None] = mapped_column(Numeric(8, 5))
    on_base_percentage: Mapped[Decimal | None] = mapped_column(Numeric(8, 5))
    slugging_percentage: Mapped[Decimal | None] = mapped_column(Numeric(8, 5))
    last_game_date: Mapped[date | None] = mapped_column(Date)
    generation: Mapped[str] = mapped_column(String(64))


class PitcherGameLog(Base):
    __tablename__ = "pitcher_game_logs"
    __table_args__ = (
        UniqueConstraint("game_id", "pitcher_id", name="uq_pitcher_game_pitcher"),
        CheckConstraint("innings_outs >= 0", name="ck_pitcher_outs_nonnegative"),
        Index("ix_pitcher_history", "season", "pitcher_id", "game_date"),
        Index("ix_pitcher_opponent_date", "pitcher_id", "opponent_team_id", "game_date"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    game_id: Mapped[int] = mapped_column(ForeignKey("games.id"))
    game_date: Mapped[date] = mapped_column(Date)
    season: Mapped[int] = mapped_column(Integer)
    pitcher_id: Mapped[int] = mapped_column(ForeignKey("players.id"))
    team_id: Mapped[int | None] = mapped_column(ForeignKey("teams.id"))
    opponent_team_id: Mapped[int | None] = mapped_column(ForeignKey("teams.id"))
    source: Mapped[str] = mapped_column(String(32))
    is_starter: Mapped[bool] = mapped_column(Boolean)
    innings_outs: Mapped[int] = mapped_column(Integer)
    pitch_count: Mapped[int | None] = mapped_column(Integer)
    batters_faced: Mapped[int] = mapped_column(Integer)
    hits: Mapped[int] = mapped_column(Integer)
    walks: Mapped[int] = mapped_column(Integer)
    hit_by_pitch: Mapped[int] = mapped_column(Integer)
    strikeouts: Mapped[int] = mapped_column(Integer)
    home_runs: Mapped[int] = mapped_column(Integer)
    runs: Mapped[int] = mapped_column(Integer)
    earned_runs: Mapped[int] = mapped_column(Integer)


class PitcherSeasonSummary(Base):
    __tablename__ = "pitcher_season_summaries"

    season: Mapped[int] = mapped_column(Integer, primary_key=True)
    pitcher_id: Mapped[int] = mapped_column(ForeignKey("players.id"), primary_key=True)
    games: Mapped[int] = mapped_column(Integer)
    starts: Mapped[int] = mapped_column(Integer)
    innings_outs: Mapped[int] = mapped_column(BigInteger)
    pitch_count: Mapped[int] = mapped_column(BigInteger)
    batters_faced: Mapped[int] = mapped_column(BigInteger)
    hits: Mapped[int] = mapped_column(BigInteger)
    walks: Mapped[int] = mapped_column(BigInteger)
    hit_by_pitch: Mapped[int] = mapped_column(BigInteger)
    strikeouts: Mapped[int] = mapped_column(BigInteger)
    home_runs: Mapped[int] = mapped_column(BigInteger)
    runs: Mapped[int] = mapped_column(BigInteger)
    earned_runs: Mapped[int] = mapped_column(BigInteger)
    earned_run_average: Mapped[Decimal | None] = mapped_column(Numeric(8, 3))
    whip: Mapped[Decimal | None] = mapped_column(Numeric(8, 3))
    last_game_date: Mapped[date | None] = mapped_column(Date)
    generation: Mapped[str] = mapped_column(String(64))


class LiveGameContact(Base):
    __tablename__ = "live_game_contacts"
    __table_args__ = (UniqueConstraint("game_id", "play_key"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    game_id: Mapped[int] = mapped_column(ForeignKey("games.id"))
    play_key: Mapped[str] = mapped_column(String(160))
    play_index: Mapped[int | None] = mapped_column(Integer)
    inning: Mapped[int | None] = mapped_column(Integer)
    half_inning: Mapped[str | None] = mapped_column(String(16))
    batter_id: Mapped[int | None] = mapped_column(ForeignKey("players.id"))
    pitcher_id: Mapped[int | None] = mapped_column(ForeignKey("players.id"))
    result_type: Mapped[str | None] = mapped_column(String(64))
    description: Mapped[str | None] = mapped_column(Text)
    runs_scored: Mapped[int | None] = mapped_column(Integer)
    launch_speed: Mapped[Decimal | None] = mapped_column(Numeric(8, 3))
    launch_angle: Mapped[Decimal | None] = mapped_column(Numeric(8, 3))
    distance: Mapped[Decimal | None] = mapped_column(Numeric(10, 3))
    provider_residual: Mapped[dict[str, Any] | None] = mapped_column(JSON_TYPE)
    source_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class BullpenProjectionRun(Base):
    __tablename__ = "bullpen_projection_runs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    game_date: Mapped[date] = mapped_column(Date)
    generation: Mapped[str] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    active: Mapped[bool] = mapped_column(Boolean, default=False)


class BullpenProjectionItem(Base):
    __tablename__ = "bullpen_projection_items"
    __table_args__ = (UniqueConstraint("run_id", "game_id", "team_id", "pitcher_id"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("bullpen_projection_runs.id"))
    game_id: Mapped[int] = mapped_column(ForeignKey("games.id"))
    team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"))
    pitcher_id: Mapped[int] = mapped_column(ForeignKey("players.id"))
    projected_role: Mapped[str | None] = mapped_column(String(64))
    availability_score: Mapped[Decimal | None] = mapped_column(Numeric(8, 5))
    availability_label: Mapped[str | None] = mapped_column(String(32))
    appearance_probability: Mapped[Decimal | None] = mapped_column(Numeric(8, 5))
    expected_batters_faced_min: Mapped[int | None] = mapped_column(Integer)
    expected_batters_faced_max: Mapped[int | None] = mapped_column(Integer)
    recent_workload: Mapped[str | None] = mapped_column(Text)
    reason: Mapped[str | None] = mapped_column(Text)


class RefreshRun(Base):
    __tablename__ = "refresh_runs"
    __table_args__ = (
        Index("ix_refresh_runs_status_created", "status", "created_at"),
        Index("ix_refresh_runs_heartbeat", "status", "heartbeat_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(128), unique=True)
    task_name: Mapped[str | None] = mapped_column(String(96))
    source: Mapped[str] = mapped_column(String(64))
    scope: Mapped[str] = mapped_column(String(160))
    status: Mapped[str] = mapped_column(String(32))
    attempt: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=5)
    games_checked: Mapped[int] = mapped_column(Integer, default=0)
    games_processed: Mapped[int] = mapped_column(Integer, default=0)
    facts_loaded: Mapped[int] = mapped_column(BigInteger, default=0)
    input_payload: Mapped[dict[str, Any]] = mapped_column(JSON_TYPE, default=dict)
    result_payload: Mapped[dict[str, Any] | None] = mapped_column(JSON_TYPE)
    error_code: Mapped[str | None] = mapped_column(String(96))
    message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    dead_lettered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class RefreshRunItem(Base):
    __tablename__ = "refresh_run_items"
    __table_args__ = (
        UniqueConstraint("run_id", "item_key", "attempt"),
        Index("ix_refresh_run_items_status_created", "status", "created_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(
        ForeignKey("refresh_runs.id", ondelete="CASCADE")
    )
    item_key: Mapped[str] = mapped_column(String(192))
    status: Mapped[str] = mapped_column(String(32))
    attempt: Mapped[int] = mapped_column(Integer)
    error_code: Mapped[str | None] = mapped_column(String(96))
    message: Mapped[str | None] = mapped_column(Text)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON_TYPE, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ProcessingCheckpoint(Base):
    __tablename__ = "processing_checkpoints"

    source: Mapped[str] = mapped_column(String(64), primary_key=True)
    scope: Mapped[str] = mapped_column(String(160), primary_key=True)
    watermark: Mapped[str] = mapped_column(String(256))
    source_version: Mapped[str | None] = mapped_column(String(128))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class DataSourceStatus(Base):
    __tablename__ = "data_source_status"

    source: Mapped[str] = mapped_column(String(64), primary_key=True)
    watermark: Mapped[str | None] = mapped_column(String(256))
    freshness_status: Mapped[str] = mapped_column(String(32))
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_failure_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    detail: Mapped[str | None] = mapped_column(Text)


class SourceArtifact(Base):
    __tablename__ = "source_artifacts"
    __table_args__ = (UniqueConstraint("source", "generation", "sha256"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    source: Mapped[str] = mapped_column(String(64))
    generation: Mapped[str] = mapped_column(String(128))
    uri: Mapped[str] = mapped_column(Text)
    sha256: Mapped[str] = mapped_column(String(64))
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    source_version: Mapped[str | None] = mapped_column(String(128))
    inventory: Mapped[dict[str, Any]] = mapped_column(JSON_TYPE)
