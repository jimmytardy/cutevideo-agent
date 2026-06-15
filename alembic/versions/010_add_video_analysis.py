"""add video_analysis to critic_reports

Revision ID: 010
Revises: 009
Create Date: 2026-06-13
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "010"
down_revision = "009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "critic_reports",
        sa.Column("video_analysis", JSONB, nullable=True),
    )


def downgrade() -> None:
    op.drop_column("critic_reports", "video_analysis")
