"""add error_message to projects

Revision ID: 008
Revises: 007
Create Date: 2026-06-13
"""
from alembic import op
import sqlalchemy as sa

revision = "008"
down_revision = "007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("projects", sa.Column("error_message", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("projects", "error_message")
