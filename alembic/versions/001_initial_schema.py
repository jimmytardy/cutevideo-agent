"""Initial schema

Revision ID: 001
Revises:
Create Date: 2026-01-01 00:00:00.000000
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB, TIMESTAMPTZ

revision = "001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "projects",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("theme", sa.String(), nullable=False),
        sa.Column("title", sa.String(), nullable=True),
        sa.Column("target_duration_seconds", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(), nullable=False, server_default="pending"),
        sa.Column("config", JSONB(), nullable=True),
        sa.Column("created_at", TIMESTAMPTZ(), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", TIMESTAMPTZ(), nullable=False, server_default=sa.text("now()")),
    )

    op.create_table(
        "scenarios",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("project_id", UUID(as_uuid=True), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("segments", JSONB(), nullable=True),
        sa.Column("total_duration_s", sa.Integer(), nullable=True),
        sa.Column("iteration", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", TIMESTAMPTZ(), nullable=False, server_default=sa.text("now()")),
    )

    op.create_table(
        "media_assets",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("project_id", UUID(as_uuid=True), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("segment_order", sa.Integer(), nullable=True),
        sa.Column("source", sa.String(), nullable=True),
        sa.Column("source_url", sa.String(), nullable=True),
        sa.Column("local_path", sa.String(), nullable=True),
        sa.Column("license", sa.String(), nullable=True),
        sa.Column("attribution", sa.String(), nullable=True),
        sa.Column("asset_type", sa.String(), nullable=True),
        sa.Column("selected", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("created_at", TIMESTAMPTZ(), nullable=False, server_default=sa.text("now()")),
    )

    op.create_table(
        "audio_files",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("project_id", UUID(as_uuid=True), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("segment_order", sa.Integer(), nullable=True),
        sa.Column("local_path", sa.String(), nullable=True),
        sa.Column("duration_s", sa.Float(), nullable=True),
        sa.Column("tts_engine", sa.String(), nullable=True),
        sa.Column("voice", sa.String(), nullable=True),
        sa.Column("transcript", sa.String(), nullable=True),
        sa.Column("created_at", TIMESTAMPTZ(), nullable=False, server_default=sa.text("now()")),
    )

    op.create_table(
        "videos",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("project_id", UUID(as_uuid=True), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("video_type", sa.String(), nullable=True),
        sa.Column("local_path", sa.String(), nullable=True),
        sa.Column("duration_s", sa.Float(), nullable=True),
        sa.Column("iteration", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("status", sa.String(), nullable=False, server_default="draft"),
        sa.Column("created_at", TIMESTAMPTZ(), nullable=False, server_default=sa.text("now()")),
    )

    op.create_table(
        "critic_reports",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("video_id", UUID(as_uuid=True), sa.ForeignKey("videos.id"), nullable=False),
        sa.Column("iteration", sa.Integer(), nullable=True),
        sa.Column("decision", sa.String(), nullable=True),
        sa.Column("global_score", sa.Integer(), nullable=True),
        sa.Column("feedback", JSONB(), nullable=True),
        sa.Column("requested_changes", JSONB(), nullable=True),
        sa.Column("created_at", TIMESTAMPTZ(), nullable=False, server_default=sa.text("now()")),
    )

    op.create_table(
        "agent_runs",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("project_id", UUID(as_uuid=True), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("agent_name", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=True),
        sa.Column("iteration", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("input_json", JSONB(), nullable=True),
        sa.Column("output_json", JSONB(), nullable=True),
        sa.Column("error", sa.String(), nullable=True),
        sa.Column("started_at", TIMESTAMPTZ(), nullable=True),
        sa.Column("ended_at", TIMESTAMPTZ(), nullable=True),
    )

    op.create_table(
        "publications",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("video_id", UUID(as_uuid=True), sa.ForeignKey("videos.id"), nullable=False),
        sa.Column("platform", sa.String(), nullable=True),
        sa.Column("platform_video_id", sa.String(), nullable=True),
        sa.Column("platform_url", sa.String(), nullable=True),
        sa.Column("title", sa.String(), nullable=True),
        sa.Column("description", sa.String(), nullable=True),
        sa.Column("hashtags", JSONB(), nullable=True),
        sa.Column("published_at", TIMESTAMPTZ(), nullable=True),
        sa.Column("status", sa.String(), nullable=True),
    )

    op.create_table(
        "analytics",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("publication_id", UUID(as_uuid=True), sa.ForeignKey("publications.id"), nullable=False),
        sa.Column("views", sa.BigInteger(), nullable=True),
        sa.Column("likes", sa.Integer(), nullable=True),
        sa.Column("comments", sa.Integer(), nullable=True),
        sa.Column("shares", sa.Integer(), nullable=True),
        sa.Column("watch_time_seconds", sa.BigInteger(), nullable=True),
        sa.Column("retention_percent", sa.Float(), nullable=True),
        sa.Column("revenue_eur", sa.Float(), nullable=True),
        sa.Column("fetched_at", TIMESTAMPTZ(), nullable=False, server_default=sa.text("now()")),
    )

    op.create_index("ix_projects_status", "projects", ["status"])
    op.create_index("ix_agent_runs_project_id", "agent_runs", ["project_id"])
    op.create_index("ix_agent_runs_agent_name", "agent_runs", ["agent_name"])
    op.create_index("ix_media_assets_project_id", "media_assets", ["project_id"])
    op.create_index("ix_videos_project_id", "videos", ["project_id"])


def downgrade() -> None:
    op.drop_table("analytics")
    op.drop_table("publications")
    op.drop_table("agent_runs")
    op.drop_table("critic_reports")
    op.drop_table("videos")
    op.drop_table("audio_files")
    op.drop_table("media_assets")
    op.drop_table("scenarios")
    op.drop_table("projects")
