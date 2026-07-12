"""Create the normalized PostgreSQL shadow schema.

Revision ID: 0002_normalized_shadow_schema
Revises: 0001_scaffold
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002_normalized_shadow_schema"
down_revision: str | None = "0001_scaffold"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "teams",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("source_key", sa.String(160), nullable=False),
        sa.Column("abbreviation", sa.String(16)),
        sa.Column("provider_team_id", sa.BigInteger()),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("source_version", sa.String(64), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("abbreviation"),
        sa.UniqueConstraint("provider_team_id"),
        sa.UniqueConstraint("source_key"),
    )
    op.create_table(
        "players",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("provider_player_id", sa.BigInteger(), nullable=False),
        sa.Column("retrosheet_player_id", sa.String(32)),
        sa.Column("name", sa.String(200)),
        sa.Column("active_status", sa.String(32), nullable=False),
        sa.Column("source_updated_at", sa.DateTime(timezone=True)),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("provider_player_id"),
        sa.UniqueConstraint("retrosheet_player_id"),
    )
    op.create_table(
        "games",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("source_game_id", sa.String(80), nullable=False),
        sa.Column("mlb_game_pk", sa.BigInteger()),
        sa.Column("retrosheet_game_id", sa.String(32)),
        sa.Column("legacy_game_pk", sa.BigInteger(), nullable=False),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("source_version", sa.String(64), nullable=False),
        sa.Column("game_date", sa.Date(), nullable=False),
        sa.Column("season", sa.Integer(), nullable=False),
        sa.Column("away_team_id", sa.BigInteger(), nullable=False),
        sa.Column("home_team_id", sa.BigInteger(), nullable=False),
        sa.Column("away_probable_pitcher_id", sa.BigInteger()),
        sa.Column("home_probable_pitcher_id", sa.BigInteger()),
        sa.Column("game_status", sa.String(64)),
        sa.Column("source_updated_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("source_game_id LIKE '%:%'", name="ck_games_canonical_id"),
        sa.CheckConstraint("season BETWEEN 1800 AND 2200", name="ck_games_season"),
        sa.ForeignKeyConstraint(["away_team_id"], ["teams.id"]),
        sa.ForeignKeyConstraint(["home_team_id"], ["teams.id"]),
        sa.ForeignKeyConstraint(["away_probable_pitcher_id"], ["players.id"]),
        sa.ForeignKeyConstraint(["home_probable_pitcher_id"], ["players.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("legacy_game_pk"),
        sa.UniqueConstraint("mlb_game_pk"),
        sa.UniqueConstraint("retrosheet_game_id"),
        sa.UniqueConstraint("source_game_id"),
    )
    op.create_index("ix_games_game_date", "games", ["game_date"])
    op.create_index("ix_games_home_date", "games", ["home_team_id", "game_date"])
    op.create_index("ix_games_away_date", "games", ["away_team_id", "game_date"])
    op.create_table(
        "batter_pitcher_game_logs",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("game_id", sa.BigInteger(), nullable=False),
        sa.Column("game_date", sa.Date(), nullable=False),
        sa.Column("season", sa.Integer(), nullable=False),
        sa.Column("batter_id", sa.BigInteger(), nullable=False),
        sa.Column("pitcher_id", sa.BigInteger(), nullable=False),
        sa.Column("batting_team_id", sa.BigInteger()),
        sa.Column("pitching_team_id", sa.BigInteger()),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("pa", sa.Integer(), nullable=False),
        sa.Column("ab", sa.Integer(), nullable=False),
        sa.Column("hits", sa.Integer(), nullable=False),
        sa.Column("doubles", sa.Integer(), nullable=False),
        sa.Column("triples", sa.Integer(), nullable=False),
        sa.Column("walks", sa.Integer(), nullable=False),
        sa.Column("hit_by_pitch", sa.Integer(), nullable=False),
        sa.Column("strikeouts", sa.Integer(), nullable=False),
        sa.Column("home_runs", sa.Integer(), nullable=False),
        sa.Column("rbi", sa.Integer(), nullable=False),
        sa.Column("sacrifice_flies", sa.Integer(), nullable=False),
        sa.Column("total_bases", sa.Integer(), nullable=False),
        sa.CheckConstraint("pa >= 0 AND ab >= 0 AND hits >= 0", name="ck_bvp_nonnegative"),
        sa.ForeignKeyConstraint(["batter_id"], ["players.id"]),
        sa.ForeignKeyConstraint(["batting_team_id"], ["teams.id"]),
        sa.ForeignKeyConstraint(["game_id"], ["games.id"]),
        sa.ForeignKeyConstraint(["pitcher_id"], ["players.id"]),
        sa.ForeignKeyConstraint(["pitching_team_id"], ["teams.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "game_id", "batter_id", "pitcher_id", name="uq_bvp_game_batter_pitcher"
        ),
    )
    op.create_index(
        "ix_bvp_batter_pitcher_date",
        "batter_pitcher_game_logs",
        ["batter_id", "pitcher_id", "game_date"],
    )
    op.create_index(
        "ix_bvp_season_batter_date",
        "batter_pitcher_game_logs",
        ["season", "batter_id", "game_date"],
    )
    op.create_table(
        "batter_pitcher_summaries",
        sa.Column("batter_id", sa.BigInteger(), nullable=False),
        sa.Column("pitcher_id", sa.BigInteger(), nullable=False),
        *[
            sa.Column(name, sa.BigInteger(), nullable=False)
            for name in (
                "pa",
                "ab",
                "hits",
                "doubles",
                "triples",
                "walks",
                "hit_by_pitch",
                "strikeouts",
                "home_runs",
                "rbi",
                "sacrifice_flies",
                "total_bases",
            )
        ],
        sa.Column("batting_average", sa.Numeric(8, 5)),
        sa.Column("on_base_percentage", sa.Numeric(8, 5)),
        sa.Column("slugging_percentage", sa.Numeric(8, 5)),
        sa.Column("last_game_date", sa.Date()),
        sa.Column("generation", sa.String(64), nullable=False),
        sa.ForeignKeyConstraint(["batter_id"], ["players.id"]),
        sa.ForeignKeyConstraint(["pitcher_id"], ["players.id"]),
        sa.PrimaryKeyConstraint("batter_id", "pitcher_id"),
    )
    op.create_table(
        "pitcher_game_logs",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("game_id", sa.BigInteger(), nullable=False),
        sa.Column("game_date", sa.Date(), nullable=False),
        sa.Column("season", sa.Integer(), nullable=False),
        sa.Column("pitcher_id", sa.BigInteger(), nullable=False),
        sa.Column("team_id", sa.BigInteger()),
        sa.Column("opponent_team_id", sa.BigInteger()),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("is_starter", sa.Boolean(), nullable=False),
        sa.Column("innings_outs", sa.Integer(), nullable=False),
        sa.Column("pitch_count", sa.Integer()),
        sa.Column("batters_faced", sa.Integer(), nullable=False),
        sa.Column("hits", sa.Integer(), nullable=False),
        sa.Column("walks", sa.Integer(), nullable=False),
        sa.Column("hit_by_pitch", sa.Integer(), nullable=False),
        sa.Column("strikeouts", sa.Integer(), nullable=False),
        sa.Column("home_runs", sa.Integer(), nullable=False),
        sa.Column("runs", sa.Integer(), nullable=False),
        sa.Column("earned_runs", sa.Integer(), nullable=False),
        sa.CheckConstraint("innings_outs >= 0", name="ck_pitcher_outs_nonnegative"),
        sa.ForeignKeyConstraint(["game_id"], ["games.id"]),
        sa.ForeignKeyConstraint(["opponent_team_id"], ["teams.id"]),
        sa.ForeignKeyConstraint(["pitcher_id"], ["players.id"]),
        sa.ForeignKeyConstraint(["team_id"], ["teams.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("game_id", "pitcher_id", name="uq_pitcher_game_pitcher"),
    )
    op.create_index(
        "ix_pitcher_history", "pitcher_game_logs", ["season", "pitcher_id", "game_date"]
    )
    op.create_index(
        "ix_pitcher_opponent_date",
        "pitcher_game_logs",
        ["pitcher_id", "opponent_team_id", "game_date"],
    )
    op.create_table(
        "pitcher_season_summaries",
        sa.Column("season", sa.Integer(), nullable=False),
        sa.Column("pitcher_id", sa.BigInteger(), nullable=False),
        sa.Column("games", sa.Integer(), nullable=False),
        sa.Column("starts", sa.Integer(), nullable=False),
        *[
            sa.Column(name, sa.BigInteger(), nullable=False)
            for name in (
                "innings_outs",
                "pitch_count",
                "batters_faced",
                "hits",
                "walks",
                "hit_by_pitch",
                "strikeouts",
                "home_runs",
                "runs",
                "earned_runs",
            )
        ],
        sa.Column("earned_run_average", sa.Numeric(8, 3)),
        sa.Column("whip", sa.Numeric(8, 3)),
        sa.Column("last_game_date", sa.Date()),
        sa.Column("generation", sa.String(64), nullable=False),
        sa.ForeignKeyConstraint(["pitcher_id"], ["players.id"]),
        sa.PrimaryKeyConstraint("season", "pitcher_id"),
    )
    op.create_table(
        "live_game_contacts",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("game_id", sa.BigInteger(), nullable=False),
        sa.Column("play_key", sa.String(160), nullable=False),
        sa.Column("play_index", sa.Integer()),
        sa.Column("inning", sa.Integer()),
        sa.Column("half_inning", sa.String(16)),
        sa.Column("batter_id", sa.BigInteger()),
        sa.Column("pitcher_id", sa.BigInteger()),
        sa.Column("result_type", sa.String(64)),
        sa.Column("description", sa.Text()),
        sa.Column("runs_scored", sa.Integer()),
        sa.Column("launch_speed", sa.Numeric(8, 3)),
        sa.Column("launch_angle", sa.Numeric(8, 3)),
        sa.Column("distance", sa.Numeric(10, 3)),
        sa.Column("provider_residual", postgresql.JSONB(astext_type=sa.Text())),
        sa.Column("source_updated_at", sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(["batter_id"], ["players.id"]),
        sa.ForeignKeyConstraint(["game_id"], ["games.id"]),
        sa.ForeignKeyConstraint(["pitcher_id"], ["players.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("game_id", "play_key"),
    )
    op.create_table(
        "bullpen_projection_runs",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("game_date", sa.Date(), nullable=False),
        sa.Column("generation", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("generation"),
    )
    op.create_table(
        "bullpen_projection_items",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("run_id", sa.BigInteger(), nullable=False),
        sa.Column("game_id", sa.BigInteger(), nullable=False),
        sa.Column("team_id", sa.BigInteger(), nullable=False),
        sa.Column("pitcher_id", sa.BigInteger(), nullable=False),
        sa.Column("projected_role", sa.String(64)),
        sa.Column("availability_score", sa.Numeric(8, 5)),
        sa.Column("availability_label", sa.String(32)),
        sa.Column("appearance_probability", sa.Numeric(8, 5)),
        sa.Column("expected_batters_faced_min", sa.Integer()),
        sa.Column("expected_batters_faced_max", sa.Integer()),
        sa.Column("recent_workload", sa.Text()),
        sa.Column("reason", sa.Text()),
        sa.ForeignKeyConstraint(["game_id"], ["games.id"]),
        sa.ForeignKeyConstraint(["pitcher_id"], ["players.id"]),
        sa.ForeignKeyConstraint(["run_id"], ["bullpen_projection_runs.id"]),
        sa.ForeignKeyConstraint(["team_id"], ["teams.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id", "game_id", "team_id", "pitcher_id"),
    )
    op.create_table(
        "refresh_runs",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("source", sa.String(64), nullable=False),
        sa.Column("scope", sa.String(160), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("games_checked", sa.Integer(), nullable=False),
        sa.Column("games_processed", sa.Integer(), nullable=False),
        sa.Column("facts_loaded", sa.BigInteger(), nullable=False),
        sa.Column("message", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_refresh_runs_status_created", "refresh_runs", ["status", "created_at"])
    op.create_table(
        "processing_checkpoints",
        sa.Column("source", sa.String(64), nullable=False),
        sa.Column("scope", sa.String(160), nullable=False),
        sa.Column("watermark", sa.String(256), nullable=False),
        sa.Column("source_version", sa.String(128)),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("source", "scope"),
    )
    op.create_table(
        "data_source_status",
        sa.Column("source", sa.String(64), nullable=False),
        sa.Column("watermark", sa.String(256)),
        sa.Column("freshness_status", sa.String(32), nullable=False),
        sa.Column("last_success_at", sa.DateTime(timezone=True)),
        sa.Column("last_failure_at", sa.DateTime(timezone=True)),
        sa.Column("detail", sa.Text()),
        sa.PrimaryKeyConstraint("source"),
    )
    op.create_table(
        "source_artifacts",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("source", sa.String(64), nullable=False),
        sa.Column("generation", sa.String(128), nullable=False),
        sa.Column("uri", sa.Text(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_version", sa.String(128)),
        sa.Column("inventory", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source", "generation", "sha256"),
    )


def downgrade() -> None:
    for table in (
        "source_artifacts",
        "data_source_status",
        "processing_checkpoints",
        "refresh_runs",
        "bullpen_projection_items",
        "bullpen_projection_runs",
        "live_game_contacts",
        "pitcher_season_summaries",
        "pitcher_game_logs",
        "batter_pitcher_summaries",
        "batter_pitcher_game_logs",
        "games",
        "players",
        "teams",
    ):
        op.drop_table(table)
