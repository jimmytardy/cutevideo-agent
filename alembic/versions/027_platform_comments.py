"""Commentaires des plateformes et réponses de l'agent `comment_reply_agent`

Une ligne par commentaire de premier niveau vu sous une vidéo publiée : dédoublonnage
(`platform` + `platform_comment_id`), heure de réponse prévue et résultat
(`pending` → `sending` → `replied` / `skipped` / `failed`), plus le fournisseur qui a publié
(`publications.provider` : `zernio`, `composio`… pour TikTok) afin de lire les commentaires au bon endroit.

Revision ID: 027
Revises: 026
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "027"
down_revision = "026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "platform_comments",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("publication_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("publications.id"), nullable=False),
        sa.Column("channel_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("channels.id"), nullable=False),
        sa.Column("platform", sa.String(), nullable=False),
        sa.Column("platform_comment_id", sa.String(), nullable=False),
        sa.Column("author_name", sa.String(), nullable=True),
        sa.Column("author_id", sa.String(), nullable=True),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("language", sa.String(), nullable=True),
        sa.Column("comment_created_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("seen_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("reply_due_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("status", sa.String(), nullable=False, server_default="pending"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("reply_text", sa.Text(), nullable=True),
        sa.Column("reply_platform_id", sa.String(), nullable=True),
        sa.Column("replied_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.UniqueConstraint("platform", "platform_comment_id", name="uq_platform_comments_platform_id"),
    )
    op.create_index("ix_platform_comments_publication_id", "platform_comments", ["publication_id"])
    op.create_index("ix_platform_comments_status_due", "platform_comments", ["status", "reply_due_at"])
    op.add_column("publications", sa.Column("provider", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("publications", "provider")
    op.drop_index("ix_platform_comments_status_due", table_name="platform_comments")
    op.drop_index("ix_platform_comments_publication_id", table_name="platform_comments")
    op.drop_table("platform_comments")
