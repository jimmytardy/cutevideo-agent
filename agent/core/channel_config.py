from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from agent.core.config import load_agent_config
from agent.core.database import Channel

THEME_SOURCE_PRIORITY: dict[str, list[str]] = {
    "histoire": ["gallica", "europeana", "wikimedia"],
    "france": ["gallica", "europeana", "wikimedia"],
    "nature": ["unsplash", "pexels", "wikimedia"],
    "animaux": ["unsplash", "pexels", "wikimedia"],
    "science": ["wikimedia", "nasa"],
    "art": ["europeana", "wikimedia"],
    "default": ["wikimedia", "unsplash", "pexels"],
}


class DailyQuotasConfig(BaseModel):
    long: int = 1
    short: int = 3


class ChannelRuntimeConfig(BaseModel):
    media_source_priority: list[str] = Field(default_factory=lambda: THEME_SOURCE_PRIORITY["default"])
    tts_voice: str = "fr-FR-HenriNeural"
    tts_fallback_voice: str = "fr-FR-DeniseNeural"
    default_tags: list[str] = Field(default_factory=list)
    youtube_category_id: str = "27"
    auto_publish: bool = False
    timezone: str = "Europe/Paris"
    daily_quotas: DailyQuotasConfig = Field(default_factory=DailyQuotasConfig)
    platform_slots: dict[str, dict[str, list[int]]] = Field(default_factory=dict)
    min_critic_score: int = 70
    max_critic_iterations: int = 3
    min_image_duration_s: int = 4
    auto_reply_comments: bool = True
    max_replies_per_run: int = 10
    max_comments_fetched: int = 50
    analytics_enabled: bool = True
    comments_enabled: bool = True
    max_publications_per_engagement_run: int = 40


def _priority_for_category(theme_category: str, overrides: dict[str, Any]) -> list[str]:
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
    default_tags = list(publishing.get("default_tags", [])) or _tags_from_channel(channel)
    raw_quotas = publishing.get("daily_quotas", {})
    daily_quotas = DailyQuotasConfig(
        long=int(raw_quotas.get("long", 1)),
        short=int(raw_quotas.get("short", 3)),
    )
    platform_slots = dict(publishing.get("platform_slots", {}))

    return ChannelRuntimeConfig(
        media_source_priority=_priority_for_category(channel.theme_category, channel_overrides),
        tts_voice=str(tts.get("voice", "fr-FR-HenriNeural")),
        tts_fallback_voice=str(tts.get("fallback_voice", "fr-FR-DeniseNeural")),
        default_tags=default_tags,
        youtube_category_id=str(publishing.get("youtube_category_id", "27")),
        auto_publish=bool(publishing.get("auto_publish", False)),
        timezone=str(publishing.get("timezone", "Europe/Paris")),
        daily_quotas=daily_quotas,
        platform_slots=platform_slots,
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
    )
