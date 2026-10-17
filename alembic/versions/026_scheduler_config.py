"""Scheduler configurable en base : activation globale, horaire et paramètres par job

Tables vides au départ : sans ligne, le scheduler est activé et chaque job
garde ses valeurs par défaut (`agent/scheduler/config.py → JOB_DEFAULTS`).

Revision ID: 026
Revises: 025
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "026"
down_revision = "025"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "scheduler_settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now()),
    )
    op.create_table(
        "scheduler_job_configs",
        sa.Column("job_id", sa.String(), primary_key=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("cron", sa.String(), nullable=False),
        sa.Column("timezone", sa.String(), nullable=False),
        sa.Column("params", postgresql.JSONB(), nullable=True),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("scheduler_job_configs")
    op.drop_table("scheduler_settings")
