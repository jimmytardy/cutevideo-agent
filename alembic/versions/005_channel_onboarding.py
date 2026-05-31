"""Channel onboarding wizard fields

Revision ID: 005
Revises: 004
Create Date: 2026-05-21
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "005"
down_revision = "004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("channels", sa.Column("theme_prompt", sa.Text(), nullable=True))
    op.add_column("channels", sa.Column("brand_kit", JSONB(), nullable=True))
    op.add_column(
        "channels",
        sa.Column("onboarding_step", sa.String(), nullable=False, server_default="complete"),
    )
    op.add_column("channels", sa.Column("tiktok_publish_defaults", JSONB(), nullable=True))
    op.add_column("channels", sa.Column("instagram_profile", JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("channels", "instagram_profile")
    op.drop_column("channels", "tiktok_publish_defaults")
    op.drop_column("channels", "onboarding_step")
    op.drop_column("channels", "brand_kit")
    op.drop_column("channels", "theme_prompt")
