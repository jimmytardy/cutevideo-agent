from __future__ import annotations

from typing import TYPE_CHECKING, Any

from agent.core.config import load_agent_config
from agent.skills.video.montage_decisions import TransitionConfig
from agent.skills.video.video_style_config import _deep_merge

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


def _channel_raw_from_ctx(ctx: "PipelineContext | None") -> dict[str, Any] | None:
    if ctx is None:
        return None
    return dict(ctx.channel.config or {})


def _montage_profile_override(channel_raw_config: dict[str, Any] | None) -> dict[str, Any]:
    if not channel_raw_config:
        return {}
    block = channel_raw_config.get("montage_profile")
    return dict(block) if isinstance(block, dict) else {}


def _short_profile_raw(channel_raw_config: dict[str, Any] | None = None) -> dict[str, Any]:
    base = load_agent_config().get("video", {}).get("short_montage_profile") or {}
    override = _montage_profile_override(channel_raw_config).get("short_montage_profile") or {}
    if isinstance(override, dict):
        return _deep_merge(dict(base), override)
    return dict(base)


def _long_profile_raw(channel_raw_config: dict[str, Any] | None = None) -> dict[str, Any]:
    base = load_agent_config().get("video", {}).get("long_montage_profile") or {}
    override = _montage_profile_override(channel_raw_config).get("long_montage_profile") or {}
    if isinstance(override, dict):
        return _deep_merge(dict(base), override)
    return dict(base)


def short_beat_slot_s(*, channel_raw_config: dict[str, Any] | None = None) -> float:
    return float(_short_profile_raw(channel_raw_config).get("beat_slot_s", 2.5))


def _format_montage_overrides_from_ctx(ctx: "PipelineContext | None") -> dict[str, Any]:
    if ctx is None or not ctx.content_plan:
        return {}
    from agent.core.editorial_formats import get_format_by_id

    fmt_id = str(ctx.content_plan.get("editorial_format_id") or "").strip()
    fmt = get_format_by_id(fmt_id, dict(ctx.channel.config or {}))
    return dict(fmt.montage_overrides) if fmt else {}


def load_format_montage_overrides(ctx: "PipelineContext | None") -> dict[str, Any]:
    """Overrides montage du format éditorial assigné au projet."""
    return _format_montage_overrides_from_ctx(ctx)


def _merge_profile_with_format(base: dict[str, Any], fmt_overrides: dict[str, Any]) -> dict[str, Any]:
    if not fmt_overrides:
        return base
    merged = dict(base)
    for key, value in fmt_overrides.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            nested = dict(merged[key])
            nested.update(value)
            merged[key] = nested
        else:
            merged[key] = value
    return merged


def short_sfx_config(*, channel_raw_config: dict[str, Any] | None = None) -> dict[str, Any]:
    return dict(_short_profile_raw(channel_raw_config).get("sfx") or {})


def long_sfx_config(*, channel_raw_config: dict[str, Any] | None = None) -> dict[str, Any]:
    return dict(_long_profile_raw(channel_raw_config).get("sfx") or {})


def long_pacing_config(
    *,
    channel_raw_config: dict[str, Any] | None = None,
    ctx: "PipelineContext | None" = None,
) -> dict[str, Any]:
    raw = _long_profile_raw(channel_raw_config)
    fmt_overrides = _format_montage_overrides_from_ctx(ctx)
    merged = _merge_profile_with_format(raw, fmt_overrides)
    return dict(merged.get("pacing") or {})


def load_sfx_config(ctx: "PipelineContext") -> dict[str, Any]:
    """Merge config SFX globale + profil short ou long + format éditorial."""
    channel_raw = _channel_raw_from_ctx(ctx)
    global_sfx = dict(load_agent_config().get("sfx") or {})
    profile_sfx = (
        short_sfx_config(channel_raw_config=channel_raw)
        if is_short_montage(ctx)
        else long_sfx_config(channel_raw_config=channel_raw)
    )
    fmt_overrides = _format_montage_overrides_from_ctx(ctx)
    fmt_sfx = dict(fmt_overrides.get("sfx") or {})
    return {**global_sfx, **profile_sfx, **fmt_sfx}


def inter_segment_flash_config(
    *,
    is_short: bool = False,
    channel_raw_config: dict[str, Any] | None = None,
    ctx: "PipelineContext | None" = None,
) -> tuple[bool, float]:
    """Flash blanc entre chapitres (long 16:9 uniquement)."""
    if is_short:
        return False, 0.0
    raw = _long_profile_raw(channel_raw_config)
    fmt_overrides = _format_montage_overrides_from_ctx(ctx)
    merged = _merge_profile_with_format(raw, fmt_overrides)
    enabled = bool(merged.get("inter_segment_flash", False))
    duration = float(merged.get("inter_segment_flash_duration_s", 0.15))
    return enabled, duration


def dynamic_recut_enabled(*, channel_raw_config: dict[str, Any] | None = None) -> bool:
    return bool(_short_profile_raw(channel_raw_config).get("dynamic_recut_enabled", False))


def load_ken_burns_config(
    *,
    is_short: bool = False,
    channel_raw_config: dict[str, Any] | None = None,
) -> dict[str, float | bool]:
    video_cfg = load_agent_config().get("video", {})
    base = dict(video_cfg.get("ken_burns") or {})
    if is_short:
        overrides = _short_profile_raw(channel_raw_config).get("ken_burns") or {}
        base.update(overrides)
    return {
        "enabled": bool(base.get("enabled", True)),
        "zoom_factor": float(base.get("zoom_factor", 0.03)),
        "pan_enabled": bool(base.get("pan_enabled", False)),
    }


def load_montage_transition_config(
    *,
    is_short: bool = False,
    channel_raw_config: dict[str, Any] | None = None,
) -> TransitionConfig:
    video_cfg = load_agent_config().get("video", {})
    if is_short:
        trans = dict(video_cfg.get("transitions") or {})
        overrides = dict(_short_profile_raw(channel_raw_config).get("transitions") or {})
        for key, value in overrides.items():
            if key in ("mood_defaults", "visual_type_defaults") and isinstance(value, dict):
                merged = dict(trans.get(key) or {})
                merged.update(value)
                trans[key] = merged
            else:
                trans[key] = value
    else:
        trans = dict(video_cfg.get("transitions") or {})
        long_overrides = _long_profile_raw(channel_raw_config).get("transitions") or {}
        if isinstance(long_overrides, dict):
            for key, value in long_overrides.items():
                if key in ("mood_defaults", "visual_type_defaults") and isinstance(value, dict):
                    merged = dict(trans.get(key) or {})
                    merged.update(value)
                    trans[key] = merged
                else:
                    trans[key] = value

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


def beat_snap_tolerance_s(
    *,
    is_short: bool = False,
    channel_raw_config: dict[str, Any] | None = None,
) -> float:
    raw = _short_profile_raw(channel_raw_config) if is_short else _long_profile_raw(channel_raw_config)
    return float(raw.get("beat_snap_tolerance_s", 0.15))


def jl_cuts_config(*, channel_raw_config: dict[str, Any] | None = None) -> dict[str, Any]:
    base = dict(load_agent_config().get("video", {}).get("jl_cuts") or {})
    override = _montage_profile_override(channel_raw_config).get("jl_cuts") or {}
    if isinstance(override, dict):
        base.update(override)
    return {
        "enabled": bool(base.get("enabled", False)),
        "max_audio_lead_s": float(base.get("max_audio_lead_s", 0.3)),
        "max_audio_trail_s": float(base.get("max_audio_trail_s", 0.3)),
    }
