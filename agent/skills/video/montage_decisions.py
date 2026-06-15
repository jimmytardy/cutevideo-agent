from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from agent.core.config import load_agent_config
from agent.core.montage_plan import BeatClipPlan, MotionStyle


@dataclass(frozen=True)
class TransitionConfig:
    enabled: bool
    duration_s: float
    catalog: frozenset[str]
    mood_defaults: dict[str, str]
    visual_type_defaults: dict[str, str]


def load_transition_config() -> TransitionConfig:
    cfg = load_agent_config().get("video", {}).get("transitions", {})
    catalog = cfg.get("catalog") or ["fade", "dissolve", "wiperight", "wipeleft"]
    return TransitionConfig(
        enabled=bool(cfg.get("enabled", True)),
        duration_s=float(cfg.get("duration_s", 0.4)),
        catalog=frozenset(str(t) for t in catalog),
        mood_defaults={
            str(k).lower(): str(v)
            for k, v in (cfg.get("mood_defaults") or {}).items()
        },
        visual_type_defaults={
            str(k).lower(): str(v)
            for k, v in (cfg.get("visual_type_defaults") or {}).items()
        },
    )


def validate_transition(name: str, config: TransitionConfig | None = None) -> str:
    cfg = config or load_transition_config()
    key = (name or "fade").strip().lower()
    if key in cfg.catalog:
        return key
    return "fade"


def resolve_transition(
    *,
    segment_mood: str,
    prev_visual_type: str,
    next_visual_type: str,
    default_transition: str = "fade",
    transition_hint: str = "",
    config: TransitionConfig | None = None,
) -> str:
    cfg = config or load_transition_config()
    if transition_hint:
        return validate_transition(transition_hint, cfg)
    mood_key = (segment_mood or "calme").lower().strip()
    if mood_key in cfg.mood_defaults:
        return validate_transition(cfg.mood_defaults[mood_key], cfg)
    for vt in (next_visual_type, prev_visual_type):
        vk = (vt or "").lower().strip()
        if vk in cfg.visual_type_defaults:
            return validate_transition(cfg.visual_type_defaults[vk], cfg)
    return validate_transition(default_transition, cfg)


def resolve_motion_style(
    visual_type: str,
    asset_type: str,
    motion_hint: str = "",
) -> MotionStyle:
    if motion_hint in ("static", "zoom_in", "zoom_out", "pan_left", "pan_right"):
        return motion_hint
    if asset_type == "video":
        vt = (visual_type or "").lower()
        if vt in ("sports_action", "wildlife_action", "archival_footage", "news_broll"):
            return "static"
    vt = (visual_type or "").lower()
    if vt in ("quote_card", "statistic_highlight", "text_card", "headline_overlay"):
        return "static"
    if vt in ("scientific_diagram", "infographic", "map", "timeline"):
        return "zoom_in"
    return "zoom_in"


def resolve_overlay_mode(visual_type: str) -> str:
    vt = (visual_type or "").lower()
    if vt in ("quote_card", "statistic_highlight", "text_card", "headline_overlay", "lower_third"):
        return "drawtext"
    from agent.skills.media_sources.ai.prompt_builder import is_diagram_visual_type

    if is_diagram_visual_type(vt):
        return "svg_overlay"
    return "none"


def clip_duration_s(plan: BeatClipPlan) -> float:
    return max(plan.timeline_end_s - plan.timeline_start_s, 0.5)


def compute_xfade_offset(
    clip_durations: list[float],
    transition_index: int,
    transition_duration: float,
) -> float:
    """Offset pour xfade entre clip transition_index et transition_index+1 (chaîne)."""
    if transition_index < 0 or transition_index >= len(clip_durations) - 1:
        return 0.0
    accumulated = sum(clip_durations[: transition_index + 1])
    return max(accumulated - (transition_index + 1) * transition_duration, 0.0)


def total_visual_duration(
    clip_durations: list[float],
    transition_duration: float,
    transitions_enabled: bool,
) -> float:
    if not clip_durations:
        return 0.0
    total = sum(clip_durations)
    if transitions_enabled and len(clip_durations) > 1:
        total -= transition_duration * (len(clip_durations) - 1)
    return total


def text_layout_from_dicts(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [dict(item) for item in items if isinstance(item, dict)]
