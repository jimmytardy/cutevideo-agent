from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from agent.core.config import load_agent_config
from agent.core.montage_plan import BeatClipPlan, ClipMetadata, MotionStyle


@dataclass(frozen=True)
class TransitionConfig:
    enabled: bool
    duration_s: float
    catalog: frozenset[str]
    mood_defaults: dict[str, str]
    visual_type_defaults: dict[str, str]


def load_transition_config(
    *,
    is_short: bool = False,
    channel_raw_config: dict[str, Any] | None = None,
) -> TransitionConfig:
    from agent.skills.video.montage_profile import load_montage_transition_config

    return load_montage_transition_config(
        is_short=is_short,
        channel_raw_config=channel_raw_config,
    )


_REVEAL_HOOKS = frozenset({"fait_surprenant", "revelateur", "révélateur", "chiffre"})
_REVEAL_VISUAL_TYPES = frozenset({"statistic_highlight", "headline_overlay"})
_IMPACT_TRANSITIONS = frozenset({"glitch", "flash_impact", "hrslice", "hlslice", "vuslice", "vdslice"})
_HIGH_ENERGY_THRESHOLD = 70
_LOW_ENERGY_THRESHOLD = 30
_ENERGY_CONTRAST_THRESHOLD = 40
_COLOR_SIMILARITY_THRESHOLD = 80.0


def validate_transition(name: str, config: TransitionConfig | None = None) -> str:
    cfg = config or load_transition_config()
    key = (name or "fade").strip().lower()
    if key in _IMPACT_TRANSITIONS or key in cfg.catalog:
        return key
    return "fade"


def _hex_to_rgb(hex_color: str) -> tuple[int, int, int] | None:
    h = hex_color.strip().lstrip("#")
    if len(h) != 6:
        return None
    try:
        return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    except ValueError:
        return None


def _colors_similar(
    colors_a: list[str],
    colors_b: list[str],
    *,
    threshold: float = _COLOR_SIMILARITY_THRESHOLD,
) -> bool:
    if not colors_a or not colors_b:
        return False
    ra = _hex_to_rgb(colors_a[0])
    rb = _hex_to_rgb(colors_b[0])
    if ra is None or rb is None:
        return False
    dist = math.sqrt(sum((a - b) ** 2 for a, b in zip(ra, rb)))
    return dist < threshold


def _transition_from_perception(
    prev_perception: ClipMetadata | None,
    next_perception: ClipMetadata | None,
    config: TransitionConfig,
) -> str | None:
    if next_perception and next_perception.composition == "text_heavy":
        return validate_transition("wiperight", config)

    if prev_perception is None or next_perception is None:
        return None

    prev_energy = prev_perception.energy if prev_perception.energy is not None else 50
    next_energy = next_perception.energy if next_perception.energy is not None else 50
    if abs(prev_energy - next_energy) >= _ENERGY_CONTRAST_THRESHOLD:
        return validate_transition("flash_impact", config)

    if (
        prev_perception.composition
        and next_perception.composition
        and prev_perception.composition == next_perception.composition
        and _colors_similar(prev_perception.dominant_colors, next_perception.dominant_colors)
    ):
        return validate_transition("fade", config)

    return None


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
    prev_perception: ClipMetadata | None = None,
    next_perception: ClipMetadata | None = None,
) -> str:
    cfg = config or load_transition_config()
    if transition_hint:
        return validate_transition(transition_hint, cfg)
    hook = (hook_type or "").strip().lower()
    if is_chapter_break or hook in _REVEAL_HOOKS:
        if hook in _REVEAL_HOOKS or next_visual_type.lower() in _REVEAL_VISUAL_TYPES:
            return validate_transition("flash_impact", cfg)
        return validate_transition("glitch", cfg)

    if prev_perception is not None or next_perception is not None:
        guided = _transition_from_perception(prev_perception, next_perception, cfg)
        if guided is not None:
            return guided

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


def _alternate_motion(style: MotionStyle, index: int) -> MotionStyle:
    for offset in range(1, len(_MOTION_CYCLE) + 1):
        candidate = _MOTION_CYCLE[(index + offset) % len(_MOTION_CYCLE)]
        if candidate != style:
            return candidate
    return style


def _apply_motion_anti_repeat(
    style: MotionStyle,
    *,
    last_motion: MotionStyle | None,
    motion_repeat_count: int,
    index: int,
) -> MotionStyle:
    if last_motion is None or style != last_motion:
        return style
    if motion_repeat_count < 2:
        return style
    return _alternate_motion(style, index)


def _motion_from_perception(perception: ClipMetadata, index: int) -> MotionStyle:
    energy = perception.energy if perception.energy is not None else 50
    composition = perception.composition

    if composition == "portrait" or perception.faces >= 1:
        return "punch_zoom" if perception.faces >= 1 else "zoom_in"

    if composition == "wide" and perception.horizon_y is not None:
        return "pan_left" if index % 2 == 0 else "pan_right"

    if composition == "detail":
        return "static" if energy <= _LOW_ENERGY_THRESHOLD else "zoom_out"

    if energy >= _HIGH_ENERGY_THRESHOLD:
        return "punch_zoom"

    return _MOTION_CYCLE[index % len(_MOTION_CYCLE)]


def resolve_motion_focus(
    perception: ClipMetadata | None,
    motion_style: MotionStyle,
) -> list[float] | None:
    if perception is None:
        return None
    if motion_style in ("static", "pan_left", "pan_right"):
        return None
    box: list[float] | None = None
    if perception.faces >= 1 and perception.face_box and len(perception.face_box) >= 4:
        box = list(perception.face_box[:4])
    elif perception.salient_box and len(perception.salient_box) >= 4:
        box = list(perception.salient_box[:4])
    return box


def resolve_motion_style(
    visual_type: str,
    asset_type: str,
    motion_hint: str = "",
    index: int = 0,
    *,
    is_short: bool = False,
    hook_type: str = "",
    perception: ClipMetadata | None = None,
    last_motion: MotionStyle | None = None,
    motion_repeat_count: int = 0,
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
    if vt in ("scientific_diagram", "infographic", "map", "timeline"):
        return "zoom_in"

    if perception is not None:
        style = _motion_from_perception(perception, index)
    else:
        style = _MOTION_CYCLE[index % len(_MOTION_CYCLE)]
        if is_short and style == "static":
            style = "zoom_in"

    return _apply_motion_anti_repeat(
        style,
        last_motion=last_motion,
        motion_repeat_count=motion_repeat_count,
        index=index,
    )


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
