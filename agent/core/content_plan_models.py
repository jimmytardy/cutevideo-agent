from __future__ import annotations

from pydantic import BaseModel, Field


class VideoTopicPlan(BaseModel):
    """Sujet mandaté pour un agent de production (long ou short dérivé)."""

    priority: int = 1
    format: str = Field(description="long | short_derived | short_standalone")
    provisional_title: str
    angle: str = Field(description="Angle éditorial en 2 lignes max")
    narrative_format: str = Field(
        description="portrait | comparaison | récit | tuto | débat | chronologie | ..."
    )
    estimated_duration_s: int
    sub_theme: str
    main_entities: list[str] = Field(default_factory=list)
    seo_keywords: list[str] = Field(default_factory=list)
    subject: str = Field(description="Sujet principal pour project.theme / scénariste")
    parent_long_index: int | None = None
    reactive_news_hook: str | None = None


class ThemeAnalysis(BaseModel):
    sub_themes: list[str] = Field(default_factory=list)
    narrative_formats: list[str] = Field(default_factory=list)
    central_figures: list[str] = Field(default_factory=list)
    good_subject_criteria: list[str] = Field(default_factory=list)


class DailyContentPlan(BaseModel):
    """Plan éditorial journalier produit par content_planner_agent."""

    plan_date: str
    production_date: str = ""
    target_publish_date: str = ""
    channel_slug: str
    theme_category: str
    long_count: int
    short_count: int
    theme_analysis: ThemeAnalysis
    long_videos: list[VideoTopicPlan] = Field(default_factory=list)
    short_videos: list[VideoTopicPlan] = Field(default_factory=list)
    selection_rationale: str = ""
    evergreen_fallback_used: bool = False
