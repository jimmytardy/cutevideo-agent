"""Add channels table and link projects/publications

Revision ID: 002
Revises: 001
Create Date: 2026-05-21
"""
from __future__ import annotations

import uuid

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

revision = "002"
down_revision = "001"
branch_labels = None
depends_on = None

DEFAULT_CHANNEL_ID = str(uuid.uuid4())


def upgrade() -> None:
    op.create_table(
        "channels",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("slug", sa.String(), nullable=False, unique=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("theme_category", sa.String(), nullable=False),
        sa.Column("niche_prompt", sa.String(), nullable=True),
        sa.Column("config", JSONB(), nullable=True),
        sa.Column("youtube_channel_id", sa.String(), nullable=True),
        sa.Column("youtube_channel_url", sa.String(), nullable=True),
        sa.Column("youtube_refresh_token", sa.String(), nullable=True),
        sa.Column("instagram_page_id", sa.String(), nullable=True),
        sa.Column("tiktok_enabled", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("composio_user_id", sa.String(), nullable=False),
        sa.Column("composio_tiktok_account_id", sa.String(), nullable=True),
        sa.Column("max_concurrent_pipelines", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )

    op.execute(
        sa.text(
            """
            INSERT INTO channels (
                id, slug, name, theme_category, niche_prompt, composio_user_id, is_active
            ) VALUES (
                CAST(:id AS uuid), 'default', 'Chaîne par défaut', 'default',
                'Vidéos éducatives généralistes', 'default', true
            )
            """
        ).bindparams(id=DEFAULT_CHANNEL_ID)
    )

    op.add_column(
        "projects",
        sa.Column("channel_id", UUID(as_uuid=True), nullable=True),
    )
    op.execute(
        sa.text("UPDATE projects SET channel_id = CAST(:cid AS uuid)").bindparams(cid=DEFAULT_CHANNEL_ID)
    )
    op.alter_column("projects", "channel_id", nullable=False)
    op.create_foreign_key(
        "fk_projects_channel_id", "projects", "channels", ["channel_id"], ["id"]
    )
    op.create_index("ix_projects_channel_id", "projects", ["channel_id"])

    op.add_column(
        "publications",
        sa.Column("channel_id", UUID(as_uuid=True), nullable=True),
    )
    op.execute(
        sa.text(
            """
            UPDATE publications p
            SET channel_id = pr.channel_id
            FROM videos v
            JOIN projects pr ON pr.id = v.project_id
            WHERE p.video_id = v.id
            """
        )
    )
    op.create_foreign_key(
        "fk_publications_channel_id",
        "publications",
        "channels",
        ["channel_id"],
        ["id"],
    )
    op.create_index("ix_channels_slug", "channels", ["slug"])


def downgrade() -> None:
    op.drop_index("ix_channels_slug", table_name="channels")
    op.drop_constraint("fk_publications_channel_id", "publications", type_="foreignkey")
    op.drop_column("publications", "channel_id")
    op.drop_index("ix_projects_channel_id", table_name="projects")
    op.drop_constraint("fk_projects_channel_id", "projects", type_="foreignkey")
    op.drop_column("projects", "channel_id")
    op.drop_table("channels")
