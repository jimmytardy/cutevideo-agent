"""subscription enable_ai_fallback by plan

Revision ID: 015
Revises: 014
Create Date: 2026-06-15
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "015"
down_revision = "014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE subscription_plans "
            "SET limits = limits || CAST(:patch AS jsonb) "
            "WHERE slug = 'free'"
        ).bindparams(patch='{"enable_ai_fallback": false}')
    )
    op.execute(
        sa.text(
            "UPDATE subscription_plans "
            "SET limits = limits || CAST(:patch AS jsonb) "
            "WHERE slug IN ('starter', 'pro', 'enterprise')"
        ).bindparams(patch='{"enable_ai_fallback": true}')
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE subscription_plans "
            "SET limits = limits - 'enable_ai_fallback'"
        )
    )
