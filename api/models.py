from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class ChannelCreate(BaseModel):
    slug: str
    name: str
    theme_category: str
    niche_prompt: str | None = None
    config: dict[str, Any] | None = None
    youtube_channel_id: str | None = None
    youtube_channel_url: str | None = None
    instagram_page_id: str | None = None
    tiktok_enabled: bool = True
    max_concurrent_pipelines: int = 1


class ChannelUpdate(BaseModel):
    name: str | None = None
    theme_category: str | None = None
    niche_prompt: str | None = None
    config: dict[str, Any] | None = None
    youtube_channel_id: str | None = None
    youtube_channel_url: str | None = None
    youtube_refresh_token: str | None = None
    instagram_page_id: str | None = None
    tiktok_enabled: bool | None = None
    max_concurrent_pipelines: int | None = None
    is_active: bool | None = None


class ChannelResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    slug: str
    name: str
    theme_category: str
    niche_prompt: str | None
    config: dict | None
    youtube_channel_id: str | None
    youtube_channel_url: str | None
    instagram_page_id: str | None
    tiktok_enabled: bool
    composio_user_id: str
    composio_tiktok_account_id: str | None
    max_concurrent_pipelines: int
    is_active: bool
    created_at: datetime
    updated_at: datetime


class ChannelIntegrationsResponse(BaseModel):
    tiktok_connected: bool
    tiktok_enabled: bool
    youtube_configured: bool
    instagram_configured: bool


class TikTokConnectResponse(BaseModel):
    redirect_url: str
    connection_id: str


class ProjectCreate(BaseModel):
    channel_id: UUID
    theme: str
    target_duration_seconds: int = 1800
    config: dict[str, Any] | None = None


class ProjectResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    channel_id: UUID
    channel_name: str | None = None
    theme: str
    title: str | None
    target_duration_seconds: int | None
    status: str
    config: dict | None
    created_at: datetime
    updated_at: datetime


class ScenarioResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    segments: list | None
    total_duration_s: int | None
    iteration: int
    created_at: datetime


class MediaAssetResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    segment_order: int | None
    source: str | None
    source_url: str | None
    local_path: str | None
    license: str | None
    attribution: str | None
    asset_type: str | None
    selected: bool
    created_at: datetime


class VideoResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    video_type: str | None
    local_path: str | None
    duration_s: float | None
    iteration: int
    status: str
    created_at: datetime


class CriticReportResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    video_id: UUID
    iteration: int | None
    decision: str | None
    global_score: int | None
    feedback: dict | None
    requested_changes: list | None
    created_at: datetime


class AgentRunResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    agent_name: str | None
    status: str | None
    iteration: int
    input_json: dict | None
    output_json: dict | None
    error: str | None
    started_at: datetime | None
    ended_at: datetime | None


class AnalyticsResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    publication_id: UUID
    views: int | None
    likes: int | None
    comments: int | None
    shares: int | None
    watch_time_seconds: int | None
    retention_percent: float | None
    revenue_eur: float | None
    fetched_at: datetime


class PublicationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    video_id: UUID
    channel_id: UUID | None
    platform: str | None
    platform_video_id: str | None
    platform_url: str | None
    title: str | None
    description: str | None
    hashtags: list | None
    published_at: datetime | None
    status: str | None
