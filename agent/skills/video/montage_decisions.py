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


def load_transition_config(*, is_short: bool = False) -> TransitionConfig:
    from agent.skills.video.montage_profile import load_montage_transition_config

    return load_montage_transition_config(is_short=is_short)


_REVEAL_HOOKS = frozenset({"fait_surprenant", "revelateur", "révélateur", "chiffre"})
_REVEAL_VISUAL_TYPES = frozenset({"statistic_highlight", "headline_overlay"})
_IMPACT_TRANSITIONS = frozenset({"glitch", "flash_impact", "hrslice", "hlslice", "vuslice", "vdslice"})


def validate_transition(name: str, config: TransitionConfig | None = None) -> str:
    cfg = config or load_transition_config()
    key = (name or "fade").strip().lower()
    if key in _IMPACT_TRANSITIONS or key in cfg.catalog:
        return key
    return "fade"


def resolve_transition(
    *,
    segment_mood: str,
    prev_visual_type: str,
    next_visual_type: str,
    default_transition: str = "fade",
    transition_hint: str = "",
    is_chapter_break: bool = False,
    hook_type: str = "",
    config: TransitionConfig | None = None,
) -> str:
    cfg = config or load_transition_config()
    if transition_hint:
        return validate_transition(transition_hint, cfg)
    hook = (hook_type or "").strip().lower()
    if is_chapter_break or hook in _REVEAL_HOOKS:
        if hook in _REVEAL_HOOKS or next_visual_type.lower() in _REVEAL_VISUAL_TYPES:
            return validate_transition("flash_impact", cfg)
        return validate_transition("glitch", cfg)
    mood_key = (segment_mood or "calme").lower().strip()
    if mood_key in cfg.mood_defaults:
        return validate_transition(cfg.mood_defaults[mood_key], cfg)
    for vt in (next_visual_type, prev_visual_type):
        vk = (vt or "").lower().strip()
        if vk in cfg.visual_type_defaults:
            return validate_transition(cfg.visual_type_defaults[vk], cfg)
    return validate_transition(default_transition, cfg)


# Cycle de mouvement Ken Burns pour les photos : alterner le sens évite l'effet
# hypnotique répétitif d'un zoom_in systématique sur toute la vidéo.
_MOTION_CYCLE: tuple[MotionStyle, ...] = ("zoom_in", "zoom_out", "pan_right", "pan_left")


def resolve_motion_style(
    visual_type: str,
    asset_type: str,
    motion_hint: str = "",
    index: int = 0,
    *,
    is_short: bool = False,
    hook_type: str = "",
) -> MotionStyle:
    if motion_hint in ("static", "zoom_in", "zoom_out", "pan_left", "pan_right", "punch_zoom"):
        return motion_hint  # type: ignore[return-value]
    vt = (visual_type or "").lower()
    hook = (hook_type or "").strip().lower()
    if vt == "statistic_highlight" or hook in _REVEAL_HOOKS:
        return "punch_zoom"
    if asset_type == "video":
        vt = (visual_type or "").lower()
        if vt in ("sports_action", "wildlife_action", "archival_footage", "news_broll"):
            return "static"
    vt = (visual_type or "").lower()
    if vt in ("quote_card", "statistic_highlight", "text_card", "headline_overlay"):
        return "static"
    # Diagrammes : zoom_in léger pour garder les labels lisibles (pas de pan).
    if vt in ("scientific_diagram", "infographic", "map", "timeline"):
        return "zoom_in"
    # Photos : alterner le mouvement selon la position du beat dans le segment.
    style = _MOTION_CYCLE[index % len(_MOTION_CYCLE)]
    if is_short and style == "static":
        return "zoom_in"
    return style


def resolve_text_animation(visual_type: str, hook_type: str = "") -> str:
    """Mappe visual_type / hook vers un style d'animation ASS."""
    from agent.skills.video.video_style_config import load_text_overlay_animation_config

    cfg = load_text_overlay_animation_config()
    if not cfg.enabled:
        return "pop_bounce"
    vt = (visual_type or "").lower().strip()
    hook = (hook_type or "").strip().lower()
    if vt in cfg.by_visual_type:
        return str(cfg.by_visual_type[vt])
    if hook in _REVEAL_HOOKS:
        return "pop_bounce+highlight"
    return "pop_bounce"


def resolve_overlay_mode(
    visual_type: str,
    on_screen_text: str = "",
    *,
    hook_type: str = "",
) -> str:
    vt = (visual_type or "").lower()
    from agent.skills.video.video_style_config import load_text_overlay_animation_config

    anim_cfg = load_text_overlay_animation_config()
    drawtext_types = (
        "quote_card",
        "statistic_highlight",
        "text_card",
        "headline_overlay",
        "lower_third",
    )
    if vt in drawtext_types or (on_screen_text and on_screen_text.strip()):
        if anim_cfg.enabled and resolve_text_animation(vt, hook_type=hook_type):
            return "ass_overlay"
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
