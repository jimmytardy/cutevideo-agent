"""Engagement agents: learning context, platform comments, analytics raw_metrics

Revision ID: 004
Revises: 003
Create Date: 2026-05-21
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB, TIMESTAMPTZ

revision = "004"
down_revision = "003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("analytics", sa.Column("raw_metrics", JSONB(), nullable=True))

    op.create_table(
        "channel_learning_context",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("channel_id", UUID(as_uuid=True), sa.ForeignKey("channels.id"), nullable=False, unique=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("insights", JSONB(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("updated_at", TIMESTAMPTZ(), nullable=False, server_default=sa.text("now()")),
    )

    op.create_table(
        "platform_comments",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("publication_id", UUID(as_uuid=True), sa.ForeignKey("publications.id"), nullable=False),
        sa.Column("platform", sa.String(), nullable=False),
        sa.Column("platform_comment_id", sa.String(), nullable=False),
        sa.Column("author_name", sa.String(), nullable=True),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("published_at", TIMESTAMPTZ(), nullable=True),
        sa.Column("status", sa.String(), nullable=False, server_default="new"),
        sa.Column("reply_text", sa.Text(), nullable=True),
        sa.Column("replied_at", TIMESTAMPTZ(), nullable=True),
        sa.Column("analysis", JSONB(), nullable=True),
        sa.Column("created_at", TIMESTAMPTZ(), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("platform", "platform_comment_id", name="uq_platform_comment"),
    )
    op.create_index("ix_platform_comments_publication_id", "platform_comments", ["publication_id"])


def downgrade() -> None:
    op.drop_index("ix_platform_comments_publication_id", table_name="platform_comments")
    op.drop_table("platform_comments")
    op.drop_table("channel_learning_context")
    op.drop_column("analytics", "raw_metrics")
