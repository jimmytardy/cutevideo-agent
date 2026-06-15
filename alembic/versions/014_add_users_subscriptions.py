"""add users, subscription plans, api keys, channel ownership

Revision ID: 014
Revises: 013
Create Date: 2026-06-15
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "014"
down_revision = "013"
branch_labels = None
depends_on = None

FREE_LIMITS = {
    "max_channels": 1,
    "max_market_analyses_per_month": 2,
    "max_projects_per_month": 5,
    "max_total_storage_bytes": 2 * 1024**3,
    "daily_quotas_short": 1,
    "max_long_duration_seconds": 900,
    "max_short_duration_s": 60,
    "production_modes": ["mixed", "shorts_only"],
    "auto_publish_allowed": False,
    "max_critic_iterations": 2,
    "tts_allowed_engines": ["edge"],
    "whisper_model": "base",
    "enable_ai_fallback": False,
}

STARTER_LIMITS = {
    **FREE_LIMITS,
    "max_channels": 3,
    "max_market_analyses_per_month": 5,
    "max_projects_per_month": 20,
    "max_total_storage_bytes": 10 * 1024**3,
    "daily_quotas_short": 3,
    "max_long_duration_seconds": 1800,
    "max_short_duration_s": 90,
    "production_modes": ["mixed", "long_only", "shorts_only"],
    "auto_publish_allowed": True,
    "max_critic_iterations": 3,
    "tts_allowed_engines": ["edge", "azure"],
    "whisper_model": "large-v3",
    "enable_ai_fallback": True,
}

PRO_LIMITS = {
    **STARTER_LIMITS,
    "max_channels": 10,
    "max_market_analyses_per_month": 15,
    "max_projects_per_month": 60,
    "max_total_storage_bytes": 50 * 1024**3,
    "daily_quotas_short": 5,
    "max_critic_iterations": 5,
    "tts_allowed_engines": ["edge", "azure", "gemini"],
}

ENTERPRISE_LIMITS = {
    **PRO_LIMITS,
    "max_channels": 50,
    "max_projects_per_month": 200,
    "max_total_storage_bytes": 200 * 1024**3,
    "daily_quotas_short": 10,
    "max_critic_iterations": 5,
}

ADMIN_LIMITS = {}


def upgrade() -> None:
    op.create_table(
        "subscription_plans",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("slug", sa.String(), nullable=False, unique=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("is_unlimited", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("limits", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("stripe_price_id", sa.String(), nullable=True),
        sa.Column("is_public", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )

    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("google_sub", sa.String(), nullable=False, unique=True),
        sa.Column("email", sa.String(), nullable=False, unique=True),
        sa.Column("display_name", sa.String(), nullable=True),
        sa.Column("avatar_url", sa.String(), nullable=True),
        sa.Column(
            "subscription_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("subscription_plans.id"),
            nullable=False,
        ),
        sa.Column(
            "subscription_started_at",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("subscription_expires_at", postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("agent_llm_preferences", postgresql.JSONB(), nullable=True),
        sa.Column("stripe_customer_id", sa.String(), nullable=True),
        sa.Column("stripe_subscription_id", sa.String(), nullable=True),
        sa.Column(
            "created_at",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )

    op.create_table(
        "user_api_keys",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("provider", sa.String(), nullable=False),
        sa.Column("encrypted_key", sa.String(), nullable=False),
        sa.Column("metadata", postgresql.JSONB(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column(
            "created_at",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.UniqueConstraint("user_id", "provider", name="uq_user_api_key_provider"),
    )

    op.create_table(
        "subscription_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("plan_slug", sa.String(), nullable=False),
        sa.Column("event_type", sa.String(), nullable=False),
        sa.Column("metadata", postgresql.JSONB(), nullable=True),
        sa.Column(
            "created_at",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )

    plan_rows = [
        ("free", "Gratuit", False, FREE_LIMITS, True, 0),
        ("starter", "Starter", False, STARTER_LIMITS, True, 1),
        ("pro", "Pro", False, PRO_LIMITS, True, 2),
        ("enterprise", "Enterprise", False, ENTERPRISE_LIMITS, True, 3),
        ("admin", "Admin", True, ADMIN_LIMITS, False, 99),
    ]
    plan_ids: dict[str, uuid.UUID] = {}
    for slug, name, unlimited, limits, is_public, sort_order in plan_rows:
        plan_id = uuid.uuid4()
        plan_ids[slug] = plan_id
        op.execute(
            sa.text(
                "INSERT INTO subscription_plans (id, slug, name, is_unlimited, limits, is_public, sort_order) "
                "VALUES (:id, :slug, :name, :unlimited, CAST(:limits AS jsonb), :is_public, :sort_order)"
            ).bindparams(
                id=plan_id,
                slug=slug,
                name=name,
                unlimited=unlimited,
                limits=json.dumps(limits),
                is_public=is_public,
                sort_order=sort_order,
            )
        )

    system_user_id = uuid.uuid4()
    now = datetime.now(timezone.utc)
    op.execute(
        sa.text(
            "INSERT INTO users (id, google_sub, email, display_name, subscription_id, "
            "subscription_started_at, is_active) "
            "VALUES (:id, :google_sub, :email, :display_name, :subscription_id, :started_at, true)"
        ).bindparams(
            id=system_user_id,
            google_sub="migration-system",
            email="system@local.cutevideo",
            display_name="System Migration",
            subscription_id=plan_ids["admin"],
            started_at=now,
        )
    )

    op.add_column(
        "channels",
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.execute(
        sa.text("UPDATE channels SET user_id = :uid").bindparams(uid=system_user_id)
    )
    op.alter_column("channels", "user_id", nullable=False)
    op.create_foreign_key("fk_channels_user_id", "channels", "users", ["user_id"], ["id"])
    op.create_index("ix_channels_user_id", "channels", ["user_id"])

    op.drop_constraint("channels_slug_key", "channels", type_="unique")
    op.create_unique_constraint("uq_channels_user_slug", "channels", ["user_id", "slug"])

    op.add_column(
        "market_analyses",
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.execute(
        sa.text("UPDATE market_analyses SET user_id = :uid").bindparams(uid=system_user_id)
    )
    op.alter_column("market_analyses", "user_id", nullable=False)
    op.create_foreign_key(
        "fk_market_analyses_user_id", "market_analyses", "users", ["user_id"], ["id"]
    )
    op.create_index("ix_market_analyses_user_id", "market_analyses", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_market_analyses_user_id", table_name="market_analyses")
    op.drop_constraint("fk_market_analyses_user_id", "market_analyses", type_="foreignkey")
    op.drop_column("market_analyses", "user_id")

    op.drop_constraint("uq_channels_user_slug", "channels", type_="unique")
    op.create_unique_constraint("channels_slug_key", "channels", ["slug"])
    op.drop_index("ix_channels_user_id", table_name="channels")
    op.drop_constraint("fk_channels_user_id", "channels", type_="foreignkey")
    op.drop_column("channels", "user_id")

    op.drop_table("subscription_events")
    op.drop_table("user_api_keys")
    op.drop_table("users")
    op.drop_table("subscription_plans")
