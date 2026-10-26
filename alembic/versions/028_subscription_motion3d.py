"""subscription motion3d_allowed by plan (motion design 3D réservé aux plans payants)

Revision ID: 028
Revises: 027
Create Date: 2026-10-26
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "028"
down_revision = "027"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE subscription_plans "
            "SET limits = limits || CAST(:patch AS jsonb) "
            "WHERE slug = 'free'"
        ).bindparams(patch='{"motion3d_allowed": false}')
    )
    op.execute(
        sa.text(
            "UPDATE subscription_plans "
            "SET limits = limits || CAST(:patch AS jsonb) "
            "WHERE slug IN ('starter', 'pro', 'enterprise')"
        ).bindparams(patch='{"motion3d_allowed": true}')
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE subscription_plans "
            "SET limits = limits - 'motion3d_allowed'"
        )
    )
