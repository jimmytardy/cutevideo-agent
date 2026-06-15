"""pipeline queue priority on subscription plans

Revision ID: 017
Revises: 016
Create Date: 2026-06-15
"""

from __future__ import annotations

import json

from alembic import op
import sqlalchemy as sa

revision = "017"
down_revision = "016"
branch_labels = None
depends_on = None

PLAN_PRIORITIES = {
    "free": 10,
    "starter": 20,
    "pro": 30,
    "enterprise": 40,
    "admin": 100,
}


def upgrade() -> None:
    conn = op.get_bind()
    for slug, priority in PLAN_PRIORITIES.items():
        row = conn.execute(
            sa.text("SELECT limits FROM subscription_plans WHERE slug = :slug"),
            {"slug": slug},
        ).fetchone()
        if row is None:
            continue
        limits = dict(row[0] or {})
        limits["pipeline_queue_priority"] = priority
        conn.execute(
            sa.text(
                "UPDATE subscription_plans SET limits = CAST(:limits AS jsonb) WHERE slug = :slug"
            ),
            {"slug": slug, "limits": json.dumps(limits)},
        )


def downgrade() -> None:
    conn = op.get_bind()
    for slug in PLAN_PRIORITIES:
        row = conn.execute(
            sa.text("SELECT limits FROM subscription_plans WHERE slug = :slug"),
            {"slug": slug},
        ).fetchone()
        if row is None:
            continue
        limits = dict(row[0] or {})
        limits.pop("pipeline_queue_priority", None)
        conn.execute(
            sa.text(
                "UPDATE subscription_plans SET limits = CAST(:limits AS jsonb) WHERE slug = :slug"
            ),
            {"slug": slug, "limits": json.dumps(limits)},
        )
