"""Add market_analyses table

Revision ID: 005
Revises: 004
Create Date: 2026-06-13
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

revision = "009"
down_revision = "008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "market_analyses",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("saturation_verdict", sa.String(), nullable=True),
        sa.Column("market_summary", sa.Text(), nullable=True),
        sa.Column("platforms_analyzed", JSONB(), nullable=True),
        sa.Column("report", JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_market_analyses_created_at", "market_analyses", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_market_analyses_created_at", table_name="market_analyses")
    op.drop_table("market_analyses")
