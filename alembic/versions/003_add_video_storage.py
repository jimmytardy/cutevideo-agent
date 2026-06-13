"""Add video storage fields for S3

Revision ID: 003
Revises: 002
Create Date: 2026-05-21
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "003"
down_revision = "002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("videos", sa.Column("storage_key", sa.String(), nullable=True))
    op.add_column("videos", sa.Column("file_size_bytes", sa.BigInteger(), nullable=True))
    op.add_column("videos", sa.Column("file_purged_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("videos", "file_purged_at")
    op.drop_column("videos", "file_size_bytes")
    op.drop_column("videos", "storage_key")
