"""Add durable job execution and per-item audit records.

Revision ID: 0003_durable_job_execution
Revises: 0002_normalized_shadow_schema
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003_durable_job_execution"
down_revision: str | None = "0002_normalized_shadow_schema"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("refresh_runs", sa.Column("idempotency_key", sa.String(128)))
    op.add_column("refresh_runs", sa.Column("task_name", sa.String(96)))
    op.add_column(
        "refresh_runs", sa.Column("attempt", sa.Integer(), nullable=False, server_default="0")
    )
    op.add_column(
        "refresh_runs", sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="5")
    )
    op.add_column(
        "refresh_runs",
        sa.Column(
            "input_payload",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
    )
    op.add_column(
        "refresh_runs",
        sa.Column("result_payload", postgresql.JSONB(astext_type=sa.Text())),
    )
    op.add_column("refresh_runs", sa.Column("error_code", sa.String(96)))
    op.add_column("refresh_runs", sa.Column("started_at", sa.DateTime(timezone=True)))
    op.add_column("refresh_runs", sa.Column("heartbeat_at", sa.DateTime(timezone=True)))
    op.add_column("refresh_runs", sa.Column("next_retry_at", sa.DateTime(timezone=True)))
    op.add_column("refresh_runs", sa.Column("dead_lettered_at", sa.DateTime(timezone=True)))
    op.add_column("refresh_runs", sa.Column("published_at", sa.DateTime(timezone=True)))
    op.create_unique_constraint(
        "uq_refresh_runs_idempotency_key", "refresh_runs", ["idempotency_key"]
    )
    op.create_index(
        "ix_refresh_runs_heartbeat", "refresh_runs", ["status", "heartbeat_at"]
    )

    op.create_table(
        "refresh_run_items",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("run_id", sa.BigInteger(), nullable=False),
        sa.Column("item_key", sa.String(192), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("error_code", sa.String(96)),
        sa.Column("message", sa.Text()),
        sa.Column(
            "payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(["run_id"], ["refresh_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id", "item_key", "attempt"),
    )
    op.create_index(
        "ix_refresh_run_items_status_created",
        "refresh_run_items",
        ["status", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_refresh_run_items_status_created", table_name="refresh_run_items")
    op.drop_table("refresh_run_items")
    op.drop_index("ix_refresh_runs_heartbeat", table_name="refresh_runs")
    op.drop_constraint("uq_refresh_runs_idempotency_key", "refresh_runs", type_="unique")
    for column in (
        "published_at",
        "dead_lettered_at",
        "next_retry_at",
        "heartbeat_at",
        "started_at",
        "error_code",
        "result_payload",
        "input_payload",
        "max_attempts",
        "attempt",
        "task_name",
        "idempotency_key",
    ):
        op.drop_column("refresh_runs", column)
