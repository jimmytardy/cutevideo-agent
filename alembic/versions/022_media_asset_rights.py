"""media asset author and requires_attribution

Revision ID: 022
Revises: 021
Create Date: 2026-06-29
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "022"
down_revision = "021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("media_assets", sa.Column("author", sa.String(), nullable=True))
    op.add_column(
        "media_assets",
        sa.Column("requires_attribution", sa.Boolean(), nullable=False, server_default="false"),
    )
    op.alter_column("media_assets", "requires_attribution", server_default=None)


def downgrade() -> None:
    op.drop_column("media_assets", "requires_attribution")
    op.drop_column("media_assets", "author")
