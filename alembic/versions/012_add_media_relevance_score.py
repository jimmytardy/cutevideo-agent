"""add relevance score to media_assets

Revision ID: 012
Revises: 011
Create Date: 2026-06-14
"""

from alembic import op
import sqlalchemy as sa

revision = "012"
down_revision = "011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("media_assets", sa.Column("relevance_score", sa.Integer(), nullable=True))
    op.add_column("media_assets", sa.Column("relevance_reason", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("media_assets", "relevance_reason")
    op.drop_column("media_assets", "relevance_score")
