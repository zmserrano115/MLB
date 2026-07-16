"""Add persisted schedule and weather read models.

Revision ID: 0004_slate_weather_read_models
Revises: 0003_durable_job_execution
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004_slate_weather_read_models"
down_revision: str | None = "0003_durable_job_execution"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "venues",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("provider_venue_id", sa.BigInteger()),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("city", sa.String(120)),
        sa.Column("latitude", sa.Numeric(10, 6)),
        sa.Column("longitude", sa.Numeric(10, 6)),
        sa.Column("elevation_ft", sa.Numeric(10, 2)),
        sa.Column("roof_type", sa.String(64)),
        sa.Column("center_field_azimuth", sa.Numeric(8, 3)),
        sa.Column("source_updated_at", sa.DateTime(timezone=True)),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("provider_venue_id"),
    )
    op.add_column("games", sa.Column("game_time_utc", sa.DateTime(timezone=True)))
    op.add_column("games", sa.Column("venue_id", sa.BigInteger()))
    op.add_column("games", sa.Column("away_score", sa.Integer()))
    op.add_column("games", sa.Column("home_score", sa.Integer()))
    op.create_foreign_key("fk_games_venue_id", "games", "venues", ["venue_id"], ["id"])

    op.create_table(
        "weather_snapshots",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("game_id", sa.BigInteger(), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("forecast_for", sa.DateTime(timezone=True)),
        sa.Column("source", sa.String(64), nullable=False),
        sa.Column("source_version", sa.String(128)),
        sa.Column("condition", sa.String(120)),
        sa.Column("temperature_f", sa.Numeric(8, 3)),
        sa.Column("feels_like_f", sa.Numeric(8, 3)),
        sa.Column("humidity_percent", sa.Numeric(6, 2)),
        sa.Column("wind_speed_mph", sa.Numeric(8, 3)),
        sa.Column("wind_direction_degrees", sa.Numeric(8, 3)),
        sa.Column("wind_out_mph", sa.Numeric(8, 3)),
        sa.Column("precipitation_probability", sa.Numeric(6, 2)),
        sa.Column("hitter_adjustment", sa.Numeric(8, 3)),
        sa.Column("pitcher_adjustment", sa.Numeric(8, 3)),
        sa.Column("edge_label", sa.String(64)),
        sa.Column("stale", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("provider_residual", postgresql.JSONB(astext_type=sa.Text())),
        sa.CheckConstraint(
            "humidity_percent IS NULL OR (humidity_percent >= 0 AND humidity_percent <= 100)",
            name="ck_weather_humidity_range",
        ),
        sa.CheckConstraint(
            "precipitation_probability IS NULL OR "
            "(precipitation_probability >= 0 AND precipitation_probability <= 100)",
            name="ck_weather_precipitation_range",
        ),
        sa.ForeignKeyConstraint(["game_id"], ["games.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("game_id", "observed_at", "source"),
    )
    op.create_index(
        "ix_weather_game_observed", "weather_snapshots", ["game_id", "observed_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_weather_game_observed", table_name="weather_snapshots")
    op.drop_table("weather_snapshots")
    op.drop_constraint("fk_games_venue_id", "games", type_="foreignkey")
    for column in ("home_score", "away_score", "venue_id", "game_time_utc"):
        op.drop_column("games", column)
    op.drop_table("venues")
