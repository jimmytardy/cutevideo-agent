from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


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
    theme_prompt: str | None = None
    creative_brief: str | None = None
    brand_kit: dict[str, Any] | None = None
    config: dict[str, Any] | None = None
    youtube_channel_id: str | None = None
    youtube_channel_url: str | None = None
    youtube_refresh_token: str | None = None
    instagram_page_id: str | None = None
    tiktok_enabled: bool | None = None
    max_concurrent_pipelines: int | None = None
    is_active: bool | None = None


class OnboardingDraftRequest(BaseModel):
    theme_prompt: str
    brand_kit: dict[str, Any]


class OnboardingYoutubeRequest(BaseModel):
    youtube_channel_id: str
    youtube_channel_url: str | None = None
    youtube_refresh_token: str | None = None


class OnboardingTikTokRequest(BaseModel):
    tiktok_publish_defaults: dict[str, Any] | None = None


class OnboardingInstagramRequest(BaseModel):
    instagram_page_id: str
    instagram_profile: dict[str, Any] | None = None


class YouTubeOAuthUrlResponse(BaseModel):
    authorization_url: str
    state: str


class YouTubeChannelItem(BaseModel):
    channel_id: str
    title: str
    description: str
    custom_url: str


class ChannelResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    slug: str
    name: str
    theme_category: str
    niche_prompt: str | None
    theme_prompt: str | None = None
    creative_brief: str | None = None
    brand_kit: dict | None = None
    onboarding_step: str = "complete"
    tiktok_publish_defaults: dict | None = None
    instagram_profile: dict | None = None
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
    tiktok_provider: str = "composio"
    tiktok_username: str | None = None
    youtube_configured: bool
    instagram_configured: bool


class TikTokConnectResponse(BaseModel):
    redirect_url: str
    connection_id: str = ""
    state: str | None = None


class TikTokFinishRequest(BaseModel):
    state: str
    params: dict[str, str] = {}


class TikTokProviderUpdate(BaseModel):
    provider: Literal["composio", "postforme", "zernio"]


class ProjectCreate(BaseModel):
    channel_id: UUID
    theme: str
    target_duration_seconds: int = 1800
    config: dict[str, Any] | None = None


class PublishRequest(BaseModel):
    platform: str


class ProjectResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    channel_id: UUID
    channel_name: str | None = None
    theme: str
    title: str | None
    target_duration_seconds: int | None
    status: str
    error_message: str | None = None
    config: dict | None
    created_at: datetime
    updated_at: datetime
    queue_position: int | None = None
    queue_length: int | None = None
    queued_at: datetime | None = None


class PipelineQueueStatusResponse(BaseModel):
    position: int
    queue_length: int
    priority: int
    queued_at: datetime | None = None
    blocked_reason: str | None = None


class PipelineQueueEntryResponse(BaseModel):
    position: int
    project_id: UUID
    channel_id: UUID
    channel_name: str | None = None
    theme: str
    title: str | None = None
    priority: int
    queued_at: str | None = None


class ProjectMetadataResponse(BaseModel):
    title: str = ""
    description: str = ""
    tags: list[str] = Field(default_factory=list)
    chapters: list[dict[str, Any]] = Field(default_factory=list)


class ThumbnailCandidateResponse(BaseModel):
    local_path: str | None = None
    prompt: str | None = None
    attribution: str | None = None
    primary: bool = False
    ctr_score: float | None = None


class ScenarioResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    segments: list | None
    total_duration_s: int | None
    iteration: int
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


class FinalPreviewResponse(BaseModel):
    video: VideoResponse | None
    stream_url: str | None
    duration_warnings: list[str] = Field(default_factory=list)


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


class ProjectConfigUpdate(BaseModel):
    max_critic_iterations: int | None = None


class AgentProgressItem(BaseModel):
    done: int
    total: int
    percent: int
    detail: str | None = None
    segments_done: int | None = None
    segments_total: int | None = None


class PipelineProgressResponse(BaseModel):
    preparation: dict[str, AgentProgressItem]
    iterations: dict[str, dict[str, AgentProgressItem]]
    post_production: dict[str, AgentProgressItem]


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
    cost_estimate_usd: float | None = None
    llm_input_tokens: int | None = None
    llm_output_tokens: int | None = None
    llm_model: str | None = None


class ProjectCostResponse(BaseModel):
    project_id: str
    total_usd: float
    cap_usd: float
    iterations_used: int
    max_iterations: int | None
    stop_reason: str = "unknown"
    by_agent: list[dict] = Field(default_factory=list)
    by_iteration: list[dict] = Field(default_factory=list)
    elapsed_s: float = 0.0


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
    scheduled_at: datetime | None = None
    scheduling_reason: dict | None = None
    published_at: datetime | None
    status: str | None
