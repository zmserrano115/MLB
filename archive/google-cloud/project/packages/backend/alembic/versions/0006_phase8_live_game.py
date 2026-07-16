"""Add worker-owned live-game snapshots and events.

Revision ID: 0006_phase8_live_game
Revises: 0005_phase7_analytics
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006_phase8_live_game"
down_revision: str | None = "0005_phase7_analytics"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "live_game_snapshots",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("game_id", sa.BigInteger(), nullable=False),
        sa.Column("version", sa.String(128), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("feed_timestamp", sa.String(64)),
        sa.Column("abstract_state", sa.String(32)),
        sa.Column("detailed_state", sa.String(80)),
        sa.Column("is_final", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("payload_size_bytes", sa.Integer(), nullable=False),
        sa.Column(
            "snapshot",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.CheckConstraint(
            "payload_size_bytes > 0 AND payload_size_bytes <= 131072",
            name="ck_live_snapshot_payload_bound",
        ),
        sa.ForeignKeyConstraint(["game_id"], ["games.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("game_id", "version", name="uq_live_snapshot_game_version"),
    )
    op.create_index(
        "ix_live_snapshot_game_observed",
        "live_game_snapshots",
        ["game_id", "observed_at"],
    )
    op.create_table(
        "live_game_events",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("game_id", sa.BigInteger(), nullable=False),
        sa.Column("event_key", sa.String(160), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("inning", sa.Integer()),
        sa.Column("half_inning", sa.String(16)),
        sa.Column("event_type", sa.String(64)),
        sa.Column("description", sa.Text()),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("source_updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["game_id"], ["games.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("game_id", "event_key", name="uq_live_event_game_key"),
    )
    op.create_index(
        "ix_live_event_game_sequence",
        "live_game_events",
        ["game_id", "sequence"],
    )


def downgrade() -> None:
    op.drop_index("ix_live_event_game_sequence", table_name="live_game_events")
    op.drop_table("live_game_events")
    op.drop_index("ix_live_snapshot_game_observed", table_name="live_game_snapshots")
    op.drop_table("live_game_snapshots")
