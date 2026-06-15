from __future__ import annotations

from datetime import datetime
from typing import Any
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


class ThemeVariantResponse(BaseModel):
    content_angle: str
    slug: str
    name: str
    theme_category: str
    niche_prompt: str
    suggested_tags: list[str] = []


class SuggestThemesRequest(BaseModel):
    prompt: str
    market_context: str | None = None


class SuggestThemesResponse(BaseModel):
    variants: list[ThemeVariantResponse]


class MarketAnalysisRequest(BaseModel):
    prompt: str
    platforms: list[str] = Field(
        default_factory=lambda: ["youtube", "tiktok", "instagram"]
    )
    region: str = "FR"
    language: str = "fr"


class PlatformInsightResponse(BaseModel):
    platform: str
    trend_summary: str
    winning_formats: list[str] = []
    audience_signals: list[str] = []
    hashtag_or_keyword_hints: list[str] = []
    data_source: str = "model_estimate"


class CompetitorProfileResponse(BaseModel):
    platform: str
    name: str
    handle_or_url: str = ""
    subscriber_count: int | None = None
    video_count: int | None = None
    positioning: str = ""
    strengths: list[str] = []
    weaknesses: list[str] = []
    content_formats: list[str] = []


class NicheOpportunityResponse(BaseModel):
    niche_name: str
    potential_score: int
    competition_level: str
    rationale: str
    differentiation_angle: str


class RecommendedThemeResponse(BaseModel):
    content_angle: str
    slug: str
    name: str
    theme_category: str
    niche_prompt: str
    suggested_tags: list[str] = []
    differentiation_score: int = 50
    competition_level: str = "medium"
    why_you_can_win: str = ""
    risks: list[str] = []


class MarketAnalysisResponse(BaseModel):
    id: UUID | None = None
    user_prompt: str
    market_summary: str
    saturation_verdict: str
    differentiation_verdict: str
    platforms_analyzed: list[str] = []
    platform_insights: list[PlatformInsightResponse] = []
    top_competitors: list[CompetitorProfileResponse] = []
    niche_opportunities: list[NicheOpportunityResponse] = []
    recommended_themes: list[RecommendedThemeResponse] = []
    avoid: list[str] = []
    next_steps: list[str] = []


class MarketAnalysisListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    prompt: str
    saturation_verdict: str | None
    market_summary: str | None
    platforms_analyzed: list[str] | None = None
    created_at: datetime


class MarketAnalysisDetailResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    prompt: str
    saturation_verdict: str | None
    market_summary: str | None
    platforms_analyzed: list[str] | None = None
    report: dict | None = None
    created_at: datetime


class GenerateBrandRequest(BaseModel):
    variant: ThemeVariantResponse
    market_context: str | None = None


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


class ResearchBriefResponse(BaseModel):
    subject_entity: str = ""
    key_facts: list[str] = Field(default_factory=list)
    timeline: list[dict[str, str]] = Field(default_factory=list)
    sources: list[dict[str, str]] = Field(default_factory=list)
    visual_anchors: list[str] = Field(default_factory=list)
    common_misconceptions: list[str] = Field(default_factory=list)
    narrative_angles: list[str] = Field(default_factory=list)
    confidence: float = 0.0
    niche_risk: str = "medium"


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
    relevance_score: int | None = None
    relevance_reason: str | None = None
    beat_index: int | None = None
    library_status: str | None = None
    generation_prompt: str | None = None
    visual_type: str | None = None
    iteration: int | None = None
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
    subtitles_available: bool
    subtitles_download_url: str | None
    subtitles_note: str | None = None


class AudioFileResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    segment_order: int | None
    local_path: str | None
    duration_s: float | None
    tts_engine: str | None
    voice: str | None
    transcript: str | None
    word_timestamps: list | None = None
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
    video_analysis: dict | None = None
    created_at: datetime


class ProjectConfigUpdate(BaseModel):
    max_critic_iterations: int | None = None
    media_validation_override: dict[str, Any] | None = None


class MediaValidationOverrideBody(BaseModel):
    must_include: list[str] = Field(default_factory=list)
    must_exclude: list[str] = Field(default_factory=list)
    validation_prompt: str | None = None
    min_relevance_score: int | None = None


class MediaValidationBriefResponse(BaseModel):
    subject_entity: str = ""
    subject_type: str = "general"
    must_include: list[str] = Field(default_factory=list)
    must_exclude: list[str] = Field(default_factory=list)
    ambiguity_warnings: list[str] = Field(default_factory=list)
    validation_prompt: str = ""
    min_relevance_score: int = 60
    niche_risk: str = "low"
    segments: dict[str, dict[str, Any]] = Field(default_factory=dict)
    override: MediaValidationOverrideBody | None = None
    source: str = "resolved"


class RegenerateMediaValidationResponse(BaseModel):
    brief: MediaValidationBriefResponse
    message: str


class MediaProgressResponse(BaseModel):
    iteration: int
    found: int
    total: int
    percent: int
    segments_done: int
    segments_total: int
    agent_status: str


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
    scheduled_at: datetime | None = None
    scheduling_reason: dict | None = None
    published_at: datetime | None
    status: str | None
