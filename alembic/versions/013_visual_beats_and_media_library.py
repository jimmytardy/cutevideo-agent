"""visual beats columns on media_assets and word_timestamps on audio_files

Revision ID: 013
Revises: 012
Create Date: 2026-06-14
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "013"
down_revision = "012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("media_assets", sa.Column("beat_index", sa.Integer(), nullable=True))
    op.add_column(
        "media_assets",
        sa.Column("library_status", sa.String(), nullable=False, server_default="selected"),
    )
    op.add_column("media_assets", sa.Column("generation_prompt", sa.String(), nullable=True))
    op.add_column("media_assets", sa.Column("visual_type", sa.String(), nullable=True))
    op.add_column(
        "media_assets",
        sa.Column("iteration", sa.Integer(), nullable=False, server_default="1"),
    )
    op.add_column(
        "audio_files",
        sa.Column("word_timestamps", postgresql.JSONB(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("audio_files", "word_timestamps")
    op.drop_column("media_assets", "iteration")
    op.drop_column("media_assets", "visual_type")
    op.drop_column("media_assets", "generation_prompt")
    op.drop_column("media_assets", "library_status")
    op.drop_column("media_assets", "beat_index")
