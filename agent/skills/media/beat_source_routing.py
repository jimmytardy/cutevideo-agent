from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from agent.core.config import load_agent_config
from agent.core.visual_beats import VisualBeat

logger = logging.getLogger(__name__)

DEFAULT_AI_ONLY_VISUAL_TYPES: frozenset[str] = frozenset({
    "scientific_diagram",
    "infographic",
    "data_chart",
    "cross_section",
    "timeline",
    "map",
    "quote_card",
    "statistic_highlight",
    "text_card",
    "headline_overlay",
    "battle_map",
    "versus_card",
    "lower_third",
    "countdown_timer",
    "ui_mockup",
    "microscope_view",
    "meme_template",
    "cartoon",
    "satirical_illustration",
    "visual_pun",
})

DEFAULT_PRIORITY_BY_VISUAL_TYPE: dict[str, list[str]] = {
    # Archives / histoire / art
    "archival_footage": ["gallica", "europeana", "wikimedia", "internet_archive"],
    "press_photo": ["wikimedia", "gallica", "europeana", "pexels"],
    "institution_building": ["wikimedia", "gallica", "europeana", "unsplash"],
    "timeline": ["wikimedia", "gallica", "europeana"],
    "portrait_historical": ["gallica", "europeana", "wikimedia"],
    "historical_artifact": ["gallica", "europeana", "wikimedia"],
    "period_reenactment": ["wikimedia", "pexels", "internet_archive"],
    "artwork": ["europeana", "wikimedia", "unsplash"],
    "museum_interior": ["europeana", "unsplash", "pexels", "wikimedia"],
    "document_closeup": ["gallica", "wikimedia", "europeana", "internet_archive"],
    # Sport
    "sports_action": ["pexels", "pixabay", "coverr", "wikimedia", "unsplash"],
    "stadium_establishing": ["pexels", "unsplash", "pixabay", "coverr", "wikimedia"],
    "sports_celebration": ["pexels", "pixabay", "coverr", "unsplash", "wikimedia"],
    "athlete_portrait": ["wikimedia", "pexels", "unsplash", "pixabay", "coverr"],
    # Entertainment / humour
    "viral_fail": ["coverr", "pexels", "pixabay", "wikimedia"],
    "reaction_clip": ["coverr", "pexels", "pixabay", "wikimedia"],
    "ranking_moment": ["coverr", "pexels", "pixabay", "wikimedia"],
    # Nature moderne
    "wildlife_action": ["unsplash", "pexels", "pixabay", "coverr", "wikimedia"],
    "macro_detail": ["unsplash", "pexels", "wikimedia", "pixabay", "coverr"],
    "underwater": ["pexels", "unsplash", "pixabay", "coverr", "wikimedia"],
    "weather_phenomenon": ["pexels", "unsplash", "coverr", "nasa", "wikimedia"],
    "habitat_wide": ["unsplash", "pexels", "pixabay", "coverr", "wikimedia"],
    "aerial": ["unsplash", "pexels", "pixabay", "coverr", "wikimedia"],
    "establishing_shot": ["unsplash", "pexels", "coverr", "wikimedia", "pixabay"],
    # Espace
    "space_photo": ["nasa", "wikimedia", "pexels"],
    "telescope_view": ["nasa", "wikimedia", "pexels", "unsplash"],
    "laboratory_scene": ["pexels", "unsplash", "coverr", "wikimedia", "pixabay"],
    # True crime
    "crime_documentary": ["wikimedia", "pexels", "internet_archive", "pixabay"],
    "courtroom": ["wikimedia", "pexels", "unsplash"],
    "evidence_detail": ["wikimedia", "pexels", "internet_archive"],
    # Actualité
    "news_broll": ["pexels", "wikimedia", "unsplash", "pixabay"],
    "protest_scene": ["wikimedia", "pexels", "unsplash"],
    "political_figure": ["wikimedia", "gallica", "europeana", "pexels"],
    "crowd_scene": ["pexels", "wikimedia", "unsplash", "pixabay"],
    # Tech / lifestyle
    "product_shot": ["pexels", "unsplash", "pixabay", "wikimedia"],
    "office_workspace": ["pexels", "unsplash", "pixabay"],
    "money_finance": ["pexels", "unsplash", "pixabay"],
    "food_closeup": ["pexels", "unsplash", "pixabay"],
    "cooking_action": ["pexels", "pixabay", "unsplash"],
}

_TAG_SOURCE_HINTS: dict[str, list[str]] = {
    "animaux": ["unsplash", "pexels", "wikimedia"],
    "nature": ["unsplash", "pexels", "pixabay", "wikimedia"],
    "sport": ["pexels", "pixabay", "wikimedia", "unsplash"],
    "true_crime": ["wikimedia", "pexels", "internet_archive"],
    "science": ["nasa", "wikimedia", "pexels"],
    "histoire": ["gallica", "europeana", "wikimedia"],
    "art": ["europeana", "wikimedia", "unsplash"],
    "tech": ["pexels", "unsplash", "pixabay"],
    "cuisine": ["pexels", "unsplash", "pixabay"],
    "humour": ["coverr", "pexels", "pixabay", "wikimedia"],
    "entertainment": ["coverr", "pexels", "pixabay", "wikimedia"],
}


@dataclass(frozen=True)
class BeatSourcePlan:
    sources: list[str]
    skip_stock: bool
    routing_reason: str


def _load_routing_config() -> tuple[dict[str, list[str]], frozenset[str]]:
    cfg = load_agent_config().get("media_sources", {})
    raw_priority = cfg.get("priority_by_visual_type", {})
    priority: dict[str, list[str]] = dict(DEFAULT_PRIORITY_BY_VISUAL_TYPE)
    if isinstance(raw_priority, dict):
        for key, sources in raw_priority.items():
            if isinstance(sources, list):
                priority[str(key)] = [str(s) for s in sources]

    raw_ai = cfg.get("ai_only_visual_types", [])
    ai_only = set(DEFAULT_AI_ONLY_VISUAL_TYPES)
    if isinstance(raw_ai, list):
        ai_only.update(str(t) for t in raw_ai)
    return priority, frozenset(ai_only)


def merge_sources(primary: list[str], fallback: list[str]) -> list[str]:
    seen: set[str] = set()
    merged: list[str] = []
    for source in primary + fallback:
        key = source.strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        merged.append(key)
    return merged


def _segment_effective_sources(segment: dict[str, Any], channel_sources: list[str]) -> list[str]:
    hint = segment.get("source_hint") or []
    if hint:
        return merge_sources([str(s) for s in hint], channel_sources)
    return list(channel_sources)


def _sources_from_editorial_tags(visual_type: str) -> list[str] | None:
    from agent.skills.media_sources.ai.prompt_builder import editorial_tags_for_type

    tags = editorial_tags_for_type(visual_type)
    for tag in tags:
        if tag in _TAG_SOURCE_HINTS:
            return list(_TAG_SOURCE_HINTS[tag])
    return None


def resolve_beat_sources(
    beat: VisualBeat,
    segment: dict[str, Any],
    channel_sources: list[str],
) -> BeatSourcePlan:
    priority_map, ai_only_types = _load_routing_config()
    vtype = beat.visual_type
    segment_fallback = _segment_effective_sources(segment, channel_sources)

    if vtype in ai_only_types:
        return BeatSourcePlan(
            sources=[],
            skip_stock=True,
            routing_reason=f"ai_only:visual_type:{vtype}",
        )

    if vtype in priority_map:
        sources = merge_sources(priority_map[vtype], channel_sources)
        return BeatSourcePlan(
            sources=sources,
            skip_stock=False,
            routing_reason=f"mapped:visual_type:{vtype}",
        )

    tag_sources = _sources_from_editorial_tags(vtype)
    if tag_sources and vtype == "custom":
        sources = merge_sources(tag_sources, segment_fallback)
        return BeatSourcePlan(
            sources=sources,
            skip_stock=False,
            routing_reason=f"tags:visual_type:{vtype}",
        )

    return BeatSourcePlan(
        sources=segment_fallback,
        skip_stock=False,
        routing_reason=f"fallback:segment_or_channel:{vtype}",
    )
