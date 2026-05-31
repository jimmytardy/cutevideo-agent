"""Publication scheduling for distribution agent

Revision ID: 006
Revises: 005
Create Date: 2026-05-21
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "006"
down_revision = "005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "publications",
        sa.Column("scheduled_at", sa.TIMESTAMP(timezone=True), nullable=True),
    )
    op.add_column(
        "publications",
        sa.Column("scheduling_reason", JSONB(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("publications", "scheduling_reason")
    op.drop_column("publications", "scheduled_at")
