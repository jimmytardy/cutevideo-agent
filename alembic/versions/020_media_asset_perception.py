"""media asset perception and file hash cache

Revision ID: 020
Revises: 019
Create Date: 2026-06-29
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect
from sqlalchemy.dialects import postgresql

revision = "020"
down_revision = "019"
branch_labels = None
depends_on = None


def _media_asset_columns() -> set[str]:
    bind = op.get_bind()
    return {col["name"] for col in inspect(bind).get_columns("media_assets")}


def _media_asset_indexes() -> set[str]:
    bind = op.get_bind()
    return {idx["name"] for idx in inspect(bind).get_indexes("media_assets")}


def upgrade() -> None:
    columns = _media_asset_columns()
    if "perception" not in columns:
        op.add_column(
            "media_assets",
            sa.Column("perception", postgresql.JSONB(), nullable=True),
        )
    if "file_hash" not in columns:
        op.add_column(
            "media_assets",
            sa.Column("file_hash", sa.String(length=64), nullable=True),
        )
    indexes = _media_asset_indexes()
    if "ix_media_assets_file_hash" not in indexes:
        op.create_index("ix_media_assets_file_hash", "media_assets", ["file_hash"])


def downgrade() -> None:
    indexes = _media_asset_indexes()
    if "ix_media_assets_file_hash" in indexes:
        op.drop_index("ix_media_assets_file_hash", table_name="media_assets")
    columns = _media_asset_columns()
    if "file_hash" in columns:
        op.drop_column("media_assets", "file_hash")
    if "perception" in columns:
        op.drop_column("media_assets", "perception")
