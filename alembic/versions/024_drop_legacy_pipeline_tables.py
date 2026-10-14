"""Suppression des tables de l'ancien pipeline Python (remplacé par Claude Studio)

Tables jamais écrites depuis le passage à Claude Studio : media_assets,
audio_files, montage_plans, analytics, platform_comments, market_analyses,
channel_learning_context ; colonne critic_reports.video_analysis ; clés API
du fournisseur `runway` (retiré).

Sauvegarde conseillée avant `alembic upgrade head` :
    pg_dump -d cutevideo --data-only -t media_assets -t audio_files -t montage_plans \\
        -t analytics -t platform_comments -t market_analyses -t channel_learning_context \\
        > legacy_pipeline_tables.sql

Le downgrade recrée la structure (sans les données).

Revision ID: 024
Revises: 023
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "024"
down_revision = "023"
branch_labels = None
depends_on = None

LEGACY_TABLES = (
    "platform_comments",
    "analytics",
    "media_assets",
    "audio_files",
    "montage_plans",
    "market_analyses",
    "channel_learning_context",
)


def upgrade() -> None:
    for table in LEGACY_TABLES:
        op.drop_table(table)
    op.drop_column("critic_reports", "video_analysis")
    op.execute("DELETE FROM user_api_keys WHERE provider = 'runway'")


def downgrade() -> None:
    op.add_column("critic_reports", sa.Column("video_analysis", postgresql.JSONB(), nullable=True))
    # asyncpg n'accepte qu'une instruction par execute.
    for statement in _LEGACY_SCHEMA.split(";"):
        if statement.strip():
            op.execute(statement)


_LEGACY_SCHEMA = """
        CREATE TABLE channel_learning_context (
            id uuid DEFAULT gen_random_uuid() PRIMARY KEY,
            channel_id uuid NOT NULL UNIQUE REFERENCES channels(id),
            summary text,
            insights jsonb,
            version integer DEFAULT 1 NOT NULL,
            updated_at timestamp with time zone DEFAULT now() NOT NULL
        );
        CREATE TABLE market_analyses (
            id uuid DEFAULT gen_random_uuid() PRIMARY KEY,
            prompt text NOT NULL,
            saturation_verdict varchar,
            market_summary text,
            platforms_analyzed jsonb,
            report jsonb,
            created_at timestamp with time zone DEFAULT now() NOT NULL,
            user_id uuid NOT NULL CONSTRAINT fk_market_analyses_user_id REFERENCES users(id)
        );
        CREATE INDEX ix_market_analyses_created_at ON market_analyses (created_at);
        CREATE INDEX ix_market_analyses_user_id ON market_analyses (user_id);
        CREATE TABLE montage_plans (
            id uuid PRIMARY KEY,
            project_id uuid NOT NULL,
            iteration integer DEFAULT 1 NOT NULL,
            plan_data jsonb,
            created_at timestamp with time zone DEFAULT now() NOT NULL
        );
        CREATE INDEX ix_montage_plans_project_id ON montage_plans (project_id);
        CREATE TABLE audio_files (
            id uuid DEFAULT gen_random_uuid() PRIMARY KEY,
            project_id uuid NOT NULL REFERENCES projects(id),
            segment_order integer,
            local_path varchar,
            duration_s double precision,
            tts_engine varchar,
            voice varchar,
            transcript varchar,
            created_at timestamp with time zone DEFAULT now() NOT NULL,
            word_timestamps jsonb,
            iteration integer DEFAULT 1 NOT NULL
        );
        CREATE INDEX ix_audio_files_project_iteration ON audio_files (project_id, iteration);
        CREATE TABLE media_assets (
            id uuid DEFAULT gen_random_uuid() PRIMARY KEY,
            project_id uuid NOT NULL REFERENCES projects(id),
            segment_order integer,
            source varchar,
            source_url varchar,
            local_path varchar,
            license varchar,
            attribution varchar,
            asset_type varchar,
            selected boolean DEFAULT false NOT NULL,
            created_at timestamp with time zone DEFAULT now() NOT NULL,
            relevance_score integer,
            relevance_reason varchar,
            beat_index integer,
            library_status varchar DEFAULT 'selected' NOT NULL,
            generation_prompt varchar,
            visual_type varchar,
            iteration integer DEFAULT 1 NOT NULL,
            duration_s double precision,
            clip_metadata jsonb,
            perception jsonb,
            file_hash varchar(64),
            author varchar,
            requires_attribution boolean NOT NULL
        );
        CREATE INDEX ix_media_assets_file_hash ON media_assets (file_hash);
        CREATE INDEX ix_media_assets_project_id ON media_assets (project_id);
        CREATE TABLE analytics (
            id uuid DEFAULT gen_random_uuid() PRIMARY KEY,
            publication_id uuid NOT NULL REFERENCES publications(id),
            views bigint,
            likes integer,
            comments integer,
            shares integer,
            watch_time_seconds bigint,
            retention_percent double precision,
            revenue_eur double precision,
            fetched_at timestamp with time zone DEFAULT now() NOT NULL,
            raw_metrics jsonb
        );
        CREATE TABLE platform_comments (
            id uuid DEFAULT gen_random_uuid() PRIMARY KEY,
            publication_id uuid NOT NULL REFERENCES publications(id),
            platform varchar NOT NULL,
            platform_comment_id varchar NOT NULL,
            author_name varchar,
            text text NOT NULL,
            published_at timestamp with time zone,
            status varchar DEFAULT 'new' NOT NULL,
            reply_text text,
            replied_at timestamp with time zone,
            analysis jsonb,
            created_at timestamp with time zone DEFAULT now() NOT NULL,
            CONSTRAINT uq_platform_comment UNIQUE (platform, platform_comment_id)
        );
        CREATE INDEX ix_platform_comments_publication_id ON platform_comments (publication_id);
"""
