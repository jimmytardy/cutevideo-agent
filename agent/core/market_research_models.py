from __future__ import annotations

from pydantic import BaseModel, Field


class CompetitorProfile(BaseModel):
    platform: str
    name: str
    handle_or_url: str = ""
    subscriber_count: int | None = None
    video_count: int | None = None
    positioning: str = ""
    strengths: list[str] = Field(default_factory=list)
    weaknesses: list[str] = Field(default_factory=list)
    content_formats: list[str] = Field(default_factory=list)


class PlatformInsight(BaseModel):
    platform: str
    trend_summary: str
    winning_formats: list[str] = Field(default_factory=list)
    audience_signals: list[str] = Field(default_factory=list)
    hashtag_or_keyword_hints: list[str] = Field(default_factory=list)
    data_source: str = Field(description="live_api | model_estimate")


class NicheOpportunity(BaseModel):
    niche_name: str
    potential_score: int = Field(ge=0, le=100)
    competition_level: str = Field(description="low | medium | high")
    rationale: str
    differentiation_angle: str


class RecommendedTheme(BaseModel):
    content_angle: str
    slug: str
    name: str
    theme_category: str
    niche_prompt: str
    suggested_tags: list[str] = Field(default_factory=list)
    differentiation_score: int = Field(ge=0, le=100, default=50)
    competition_level: str = "medium"
    why_you_can_win: str = ""
    risks: list[str] = Field(default_factory=list)


class MarketAnalysisReport(BaseModel):
    user_prompt: str
    market_summary: str
    saturation_verdict: str = Field(description="favorable | nuanced | crowded")
    differentiation_verdict: str
    platforms_analyzed: list[str] = Field(default_factory=list)
    platform_insights: list[PlatformInsight] = Field(default_factory=list)
    top_competitors: list[CompetitorProfile] = Field(default_factory=list)
    niche_opportunities: list[NicheOpportunity] = Field(default_factory=list)
    recommended_themes: list[RecommendedTheme] = Field(default_factory=list)
    avoid: list[str] = Field(default_factory=list)
    next_steps: list[str] = Field(default_factory=list)
