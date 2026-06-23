"""add iteration column to audio_files

Revision ID: 019
Revises: 018
Create Date: 2026-06-23
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "019"
down_revision = "018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "audio_files",
        sa.Column("iteration", sa.Integer(), nullable=False, server_default="1"),
    )
    op.create_index(
        "ix_audio_files_project_iteration",
        "audio_files",
        ["project_id", "iteration"],
    )


def downgrade() -> None:
    op.drop_index("ix_audio_files_project_iteration", table_name="audio_files")
    op.drop_column("audio_files", "iteration")
