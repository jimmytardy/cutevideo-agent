from __future__ import annotations

from enum import Enum
from typing import Any, Literal, Union

from pydantic import BaseModel, Field

from agent.core.config import load_agent_config
from agent.core.database import Channel

PLAN_LEGACY_ALIASES: dict[str, str] = {
    "off": "off",
    "budget": "flux_schnell",
    "balanced": "flux_pro",
    "quality": "flux_ultra",
    "flux_schnell": "flux_schnell",
    "flux_pro": "flux_pro",
    "flux_ultra": "flux_ultra",
    "imagen3_fast": "imagen3_fast",
    "imagen3": "imagen3",
}


class AiImagePlan(str, Enum):
    OFF = "off"
    FLUX_SCHNELL = "flux_schnell"
    FLUX_PRO = "flux_pro"
    FLUX_ULTRA = "flux_ultra"
    IMAGEN3_FAST = "imagen3_fast"
    IMAGEN3 = "imagen3"


class AiFallbackConfig(BaseModel):
    enabled: bool = True
    plan: AiImagePlan = AiImagePlan.FLUX_PRO
    fallback_chain: list[str] = Field(default_factory=lambda: ["imagen3"])
    max_images_per_segment: int = 2
    max_ai_images_per_video: int = 10
    max_ai_images_per_week: int | None = None
    fallback_rate_override: float | None = None

    def resolved_provider_chain(self) -> list[str]:
        if self.plan == AiImagePlan.OFF or not self.enabled:
            return []
        primary = self.plan.value
        chain = [primary]
        for item in self.fallback_chain:
            normalized = PLAN_LEGACY_ALIASES.get(item, item)
            if normalized != "off" and normalized != primary and normalized not in chain:
                chain.append(normalized)
        return chain


class RunwayConfig(BaseModel):
    enabled: bool = False
    monthly_budget_usd: float = 20.0
    cost_per_second_usd: float = 0.05  # Gen-4 Turbo ~$0.05/s at 720p
    default_duration_s: Literal[5, 10] = 5
    model: str = "gen4_turbo"
    resolution: str = "1280:720"
    max_clips_per_video: int = 3


THEME_SOURCE_PRIORITY: dict[str, list[str]] = {
    "histoire":   ["gallica", "europeana", "wikimedia", "internet_archive", "pexels"],
    "france":     ["gallica", "europeana", "wikimedia", "pexels"],
    "nature":     ["unsplash", "pexels", "pixabay", "wikimedia", "internet_archive"],
    "animaux":    ["pexels", "pixabay", "wikimedia", "internet_archive", "unsplash"],
    "science":    ["wikimedia", "nasa", "pexels", "pixabay"],
    "art":        ["europeana", "wikimedia", "unsplash"],
    "finance":    ["pexels", "unsplash", "pixabay", "wikimedia"],
    "psychologie": ["pexels", "unsplash", "pixabay", "wikimedia"],
    "true_crime": ["wikimedia", "pexels", "internet_archive", "pixabay"],
    "tech":       ["pexels", "unsplash", "pixabay", "wikimedia"],
    "default":    ["pexels", "unsplash", "pixabay", "wikimedia", "internet_archive"],
}

DEFAULT_PLATFORMS = ["youtube", "tiktok", "instagram"]


class DailyQuotasConfig(BaseModel):
    long: int = 1
    short: int = 3


class MediaSourcesConfig(BaseModel):
    priority: list[str] = Field(default_factory=list)
    min_candidates_per_segment: int = 4
    enable_ai_fallback: bool = True
    images_per_segment: int = 4
    min_width_px: int = 1280


class ChannelRuntimeConfig(BaseModel):
    media_source_priority: list[str] = Field(default_factory=lambda: THEME_SOURCE_PRIORITY["default"])
    media_sources: MediaSourcesConfig = Field(default_factory=MediaSourcesConfig)
    tts_engine: str = "azure"
    tts_voice: str = "fr-FR-HenriNeural"
    tts_fallback_voice: str = "fr-FR-DeniseNeural"
    tts_style: str = "narration-professional"
    tts_rate: str = "+0%"
    tts_pitch: str = "+0Hz"
    default_tags: list[str] = Field(default_factory=list)
    youtube_category_id: str = "27"
    auto_publish: bool = False
    timezone: str = "Europe/Paris"
    daily_quotas: DailyQuotasConfig = Field(default_factory=DailyQuotasConfig)
    platform_slots: dict[str, dict[str, list[int]]] = Field(default_factory=dict)
    enabled_platforms: list[str] = Field(default_factory=lambda: list(DEFAULT_PLATFORMS))
    production_mode: Literal["mixed", "long_only", "shorts_only"] = "mixed"
    short_duration_s: int = 90
    editorial_tone: str = "Pédagogique, accessible, engageant"
    editorial_target_audience: str = "Grand public curieux, français"
    editorial_differentiator: str = ""
    min_critic_score: int = 70
    max_critic_iterations: int = 3
    min_image_duration_s: int = 4
    music_theme: str = "default"
    auto_reply_comments: bool = True
    max_replies_per_run: int = 10
    max_comments_fetched: int = 50
    analytics_enabled: bool = True
    comments_enabled: bool = True
    max_publications_per_engagement_run: int = 40
    ai_fallback: AiFallbackConfig = Field(default_factory=AiFallbackConfig)
    runway: RunwayConfig = Field(default_factory=RunwayConfig)


def _resolve_ai_fallback(channel_overrides: dict[str, Any]) -> AiFallbackConfig:
    global_cfg = load_agent_config().get("media_sources", {}).get("ai_fallback", {})
    media_channel = channel_overrides.get("media_sources", {})
    ai_channel = media_channel.get("ai_fallback", {}) if isinstance(media_channel, dict) else {}

    raw_plan = str(ai_channel.get("plan", global_cfg.get("default_plan", "flux_pro")))
    normalized_plan = PLAN_LEGACY_ALIASES.get(raw_plan, raw_plan)
    try:
        plan = AiImagePlan(normalized_plan)
    except ValueError:
        plan = AiImagePlan.FLUX_PRO

    fallback_chain = ai_channel.get("fallback_chain") or global_cfg.get(
        "default_fallback_chain", ["imagen3"]
    )
    return AiFallbackConfig(
        enabled=bool(ai_channel.get("enabled", global_cfg.get("enabled", True))),
        plan=plan,
        fallback_chain=[str(x) for x in fallback_chain],
        max_images_per_segment=int(
            ai_channel.get("max_images_per_segment", global_cfg.get("max_images_per_segment", 2))
        ),
        max_ai_images_per_video=int(
            ai_channel.get(
                "max_ai_images_per_video",
                global_cfg.get("max_ai_images_per_video", 10),
            )
        ),
        max_ai_images_per_week=(
            int(ai_channel["max_ai_images_per_week"])
            if ai_channel.get("max_ai_images_per_week") is not None
            else global_cfg.get("max_ai_images_per_week")
        ),
        fallback_rate_override=(
            float(ai_channel["fallback_rate_override"])
            if ai_channel.get("fallback_rate_override") is not None
            else None
        ),
    )


def _priority_for_category(theme_category: str, overrides: dict[str, Any]) -> list[str]:
    ms = overrides.get("media_sources", {})
    if isinstance(ms, dict) and ms.get("priority"):
        return [str(s) for s in ms["priority"]]
    if "media_source_priority" in overrides:
        raw = overrides["media_source_priority"]
        if isinstance(raw, list):
            return [str(s) for s in raw]
    category = theme_category.lower()
    for key, sources in THEME_SOURCE_PRIORITY.items():
        if key in category:
            return sources
    global_cfg = load_agent_config().get("media_sources", {}).get("priority_by_theme", {})
    if category in global_cfg:
        return global_cfg[category]
    if "default" in global_cfg:
        return global_cfg["default"]
    return THEME_SOURCE_PRIORITY.get(category, THEME_SOURCE_PRIORITY["default"])


def _tags_from_channel(channel: Channel) -> list[str]:
    if channel.config and channel.config.get("publishing", {}).get("default_tags"):
        return list(channel.config["publishing"]["default_tags"])
    if channel.brand_kit and channel.brand_kit.get("default_tags"):
        return [str(t) for t in channel.brand_kit["default_tags"]]
    return []


def resolve_channel_config(channel: Channel) -> ChannelRuntimeConfig:
    """Fusionne agent_config.json global et channel.config (surcharges)."""
    global_cfg = load_agent_config()
    channel_overrides: dict[str, Any] = dict(channel.config or {})
    if channel.brand_kit:
        if channel.brand_kit.get("media_source_priority") and "media_source_priority" not in channel_overrides:
            channel_overrides["media_source_priority"] = channel.brand_kit["media_source_priority"]
        if channel.brand_kit.get("default_tags") and not channel_overrides.get("publishing", {}).get("default_tags"):
            channel_overrides.setdefault("publishing", {})["default_tags"] = channel.brand_kit["default_tags"]

    pipeline = {**global_cfg.get("pipeline", {}), **channel_overrides.get("pipeline", {})}
    tts = {**global_cfg.get("tts", {}), **channel_overrides.get("tts", {})}
    publishing = {**global_cfg.get("publishing", {}), **channel_overrides.get("publishing", {})}
    engagement = {**global_cfg.get("engagement", {}), **channel_overrides.get("engagement", {})}
    production = channel_overrides.get("production", {})
    editorial = channel_overrides.get("editorial", {})
    media_global = global_cfg.get("media_sources", {})
    media_channel = channel_overrides.get("media_sources", {})

    default_tags = list(publishing.get("default_tags", [])) or _tags_from_channel(channel)
    raw_quotas = publishing.get("daily_quotas", {})
    daily_quotas = DailyQuotasConfig(
        long=int(raw_quotas.get("long", 1)),
        short=int(raw_quotas.get("short", 3)),
    )
    platform_slots = dict(publishing.get("platform_slots", {}))
    enabled_platforms = list(publishing.get("enabled_platforms", DEFAULT_PLATFORMS))

    production_mode = str(production.get("mode", "mixed"))
    if production_mode not in ("mixed", "long_only", "shorts_only"):
        production_mode = "mixed"

    if production_mode == "long_only":
        daily_quotas = DailyQuotasConfig(long=daily_quotas.long, short=0)
    elif production_mode == "shorts_only":
        daily_quotas = DailyQuotasConfig(long=0, short=daily_quotas.short or 3)

    media_sources = MediaSourcesConfig(
        priority=_priority_for_category(channel.theme_category, channel_overrides),
        min_candidates_per_segment=int(
            media_channel.get("min_candidates_per_segment", pipeline.get("images_per_segment", 4))
        ),
        enable_ai_fallback=bool(media_channel.get("enable_ai_fallback", True)),
        images_per_segment=int(pipeline.get("images_per_segment", media_global.get("images_per_segment", 4))),
        min_width_px=int(media_global.get("min_width_px", 1280)),
    )

    kit = channel.brand_kit or {}
    return ChannelRuntimeConfig(
        media_source_priority=media_sources.priority,
        media_sources=media_sources,
        tts_engine=str(tts.get("engine", "azure")),
        tts_voice=str(tts.get("voice", "fr-FR-HenriNeural")),
        tts_fallback_voice=str(tts.get("fallback_voice", "fr-FR-DeniseNeural")),
        tts_style=str(tts.get("style", tts.get("default_style", "narration-professional"))),
        tts_rate=str(tts.get("rate", tts.get("default_rate", "+0%"))),
        tts_pitch=str(tts.get("pitch", "+0Hz")),
        default_tags=default_tags,
        youtube_category_id=str(publishing.get("youtube_category_id", "27")),
        auto_publish=bool(publishing.get("auto_publish", False)),
        timezone=str(publishing.get("timezone", "Europe/Paris")),
        daily_quotas=daily_quotas,
        platform_slots=platform_slots,
        enabled_platforms=enabled_platforms,
        production_mode=production_mode,  # type: ignore[arg-type]
        short_duration_s=int(production.get("short_duration_s", global_cfg.get("content_planning", {}).get("default_short_duration_s", 60))),
        editorial_tone=str(editorial.get("tone", "Pédagogique, accessible, engageant")),
        editorial_target_audience=str(editorial.get("target_audience", "Grand public curieux, français")),
        editorial_differentiator=str(editorial.get("differentiator", kit.get("content_angle", ""))),
        min_critic_score=int(pipeline.get("min_critic_score", global_cfg.get("pipeline", {}).get("min_critic_score", 70))),
        max_critic_iterations=int(
            pipeline.get("max_critic_iterations", global_cfg.get("pipeline", {}).get("max_critic_iterations", 3))
        ),
        min_image_duration_s=int(
            pipeline.get("min_image_duration_s", global_cfg.get("pipeline", {}).get("min_image_duration_s", 4))
        ),
        auto_reply_comments=bool(engagement.get("auto_reply_comments", True)),
        max_replies_per_run=int(engagement.get("max_replies_per_run", 10)),
        max_comments_fetched=int(engagement.get("max_comments_fetched", 50)),
        analytics_enabled=bool(engagement.get("analytics_enabled", True)),
        comments_enabled=bool(engagement.get("comments_enabled", True)),
        max_publications_per_engagement_run=int(
            engagement.get(
                "max_publications_per_engagement_run",
                global_cfg.get("llm", {}).get("max_publications_per_engagement_run", 40),
            )
        ),
        ai_fallback=_resolve_ai_fallback(channel_overrides),
    )
