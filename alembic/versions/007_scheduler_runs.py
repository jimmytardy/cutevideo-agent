"""Scheduler runs table

Revision ID: 007
Revises: 006
Create Date: 2026-05-31
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "007"
down_revision = "006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "scheduler_runs",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("job_id", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("started_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("ended_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("result_json", JSONB(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
    )
    op.create_index("ix_scheduler_runs_job_id", "scheduler_runs", ["job_id"])
    op.create_index("ix_scheduler_runs_started_at", "scheduler_runs", ["started_at"])


def downgrade() -> None:
    op.drop_index("ix_scheduler_runs_started_at", table_name="scheduler_runs")
    op.drop_index("ix_scheduler_runs_job_id", table_name="scheduler_runs")
    op.drop_table("scheduler_runs")
