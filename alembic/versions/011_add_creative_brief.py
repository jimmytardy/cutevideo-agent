"""add creative_brief to channels

Revision ID: 011
Revises: 010
Create Date: 2026-06-14
"""

from alembic import op
import sqlalchemy as sa

revision = "011"
down_revision = "010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("channels", sa.Column("creative_brief", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("channels", "creative_brief")
