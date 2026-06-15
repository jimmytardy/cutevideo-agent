"""montage plans table and media clip metadata

Revision ID: 016
Revises: 015
Create Date: 2026-06-15
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "016"
down_revision = "015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("media_assets", sa.Column("duration_s", sa.Float(), nullable=True))
    op.add_column(
        "media_assets",
        sa.Column("clip_metadata", postgresql.JSONB(), nullable=True),
    )
    op.create_table(
        "montage_plans",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("iteration", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("plan_data", postgresql.JSONB(), nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index("ix_montage_plans_project_id", "montage_plans", ["project_id"])


def downgrade() -> None:
    op.drop_index("ix_montage_plans_project_id", table_name="montage_plans")
    op.drop_table("montage_plans")
    op.drop_column("media_assets", "clip_metadata")
    op.drop_column("media_assets", "duration_s")
