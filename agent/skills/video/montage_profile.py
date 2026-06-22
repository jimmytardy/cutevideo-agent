from __future__ import annotations

from typing import TYPE_CHECKING, Any

from agent.core.config import load_agent_config
from agent.skills.video.montage_decisions import TransitionConfig

if TYPE_CHECKING:
    from agent.core.orchestrator import PipelineContext

_ACTION_VIDEO_TYPES = frozenset({
    "sports_action",
    "wildlife_action",
    "archival_footage",
    "news_broll",
})


def is_short_montage(ctx: "PipelineContext") -> bool:
    """True pour shorts autonomes ou montage dérivé natif."""
    from agent.core.short_format import requires_vertical_output

    return requires_vertical_output(ctx)


def _short_profile_raw() -> dict[str, Any]:
    return load_agent_config().get("video", {}).get("short_montage_profile") or {}


def short_beat_slot_s() -> float:
    return float(_short_profile_raw().get("beat_slot_s", 2.5))


def short_sfx_config() -> dict[str, Any]:
    return dict(_short_profile_raw().get("sfx") or {})


def dynamic_recut_enabled() -> bool:
    return bool(_short_profile_raw().get("dynamic_recut_enabled", False))


def load_ken_burns_config(*, is_short: bool = False) -> dict[str, float | bool]:
    video_cfg = load_agent_config().get("video", {})
    base = dict(video_cfg.get("ken_burns") or {})
    if is_short:
        overrides = (_short_profile_raw().get("ken_burns") or {})
        base.update(overrides)
    return {
        "enabled": bool(base.get("enabled", True)),
        "zoom_factor": float(base.get("zoom_factor", 0.03)),
        "pan_enabled": bool(base.get("pan_enabled", False)),
    }


def load_montage_transition_config(*, is_short: bool = False) -> TransitionConfig:
    video_cfg = load_agent_config().get("video", {})
    if is_short:
        trans = dict(video_cfg.get("transitions") or {})
        overrides = dict(_short_profile_raw().get("transitions") or {})
        for key, value in overrides.items():
            if key in ("mood_defaults", "visual_type_defaults") and isinstance(value, dict):
                merged = dict(trans.get(key) or {})
                merged.update(value)
                trans[key] = merged
            else:
                trans[key] = value
    else:
        trans = video_cfg.get("transitions") or {}

    catalog = trans.get("catalog") or ["fade", "dissolve", "wiperight", "wipeleft"]
    return TransitionConfig(
        enabled=bool(trans.get("enabled", True)),
        duration_s=float(trans.get("duration_s", 0.4)),
        catalog=frozenset(str(t) for t in catalog),
        mood_defaults={
            str(k).lower(): str(v)
            for k, v in (trans.get("mood_defaults") or {}).items()
        },
        visual_type_defaults={
            str(k).lower(): str(v)
            for k, v in (trans.get("visual_type_defaults") or {}).items()
        },
    )


def prefer_video_for_beat(ctx: "PipelineContext", visual_type: str) -> bool:
    if not is_short_montage(ctx):
        return False
    return (visual_type or "").lower().strip() in _ACTION_VIDEO_TYPES
