"""user is_admin flag (derived from unlimited plans)

Revision ID: 018
Revises: 017
Create Date: 2026-06-21
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "018"
down_revision = "017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "is_admin",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    # Backfill : tout utilisateur rattaché à un plan illimité (« admin ») devient admin.
    op.execute(
        """
        UPDATE users
        SET is_admin = true
        WHERE subscription_id IN (
            SELECT id FROM subscription_plans WHERE is_unlimited = true
        )
        """
    )


def downgrade() -> None:
    op.drop_column("users", "is_admin")
