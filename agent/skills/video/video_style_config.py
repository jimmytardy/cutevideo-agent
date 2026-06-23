from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agent.core.config import load_agent_config

_PROJECT_ROOT = Path(__file__).resolve().parents[3]


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def channel_style_overrides(channel_raw_config: dict[str, Any] | None) -> dict[str, Any]:
    """Extrait video_style / sound_design depuis Channel.config."""
    if not channel_raw_config:
        return {}
    overrides: dict[str, Any] = {}
    for key in ("video_style", "sound_design", "video", "sfx"):
        block = channel_raw_config.get(key)
        if isinstance(block, dict):
            overrides[key] = block
    return overrides


def _merged_sound_design(channel_raw_config: dict[str, Any] | None = None) -> dict[str, Any]:
    base = dict(load_agent_config().get("sound_design") or {})
    overrides = channel_style_overrides(channel_raw_config)
    sound = overrides.get("sound_design")
    if isinstance(sound, dict):
        base = _deep_merge(base, sound)
    return base


def _merged_video_config(channel_raw_config: dict[str, Any] | None = None) -> dict[str, Any]:
    base = dict(load_agent_config().get("video") or {})
    overrides = channel_style_overrides(channel_raw_config)
    video_style = overrides.get("video_style")
    if isinstance(video_style, dict):
        base = _deep_merge(base, video_style)
    video_block = overrides.get("video")
    if isinstance(video_block, dict):
        base = _deep_merge(base, video_block)
    return base


@dataclass(frozen=True)
class SfxKindConfig:
    gain_db: float
    duration_s: float


@dataclass(frozen=True)
class TextureConfig:
    grain: int = 0
    vignette: bool = False
    vignette_angle: float = 0.25
    light_leak: bool = False
    light_leak_opacity: float = 0.15
    vhs: bool = False
    vhs_shift: int = 2


@dataclass(frozen=True)
class TextOverlayAnimationConfig:
    by_visual_type: dict[str, str]
    highlight_color: str = "#FFE600"
    glow_intensity: float = 0.5
    enabled: bool = True


@dataclass(frozen=True)
class ImpactTransitionConfig:
    glitch_frames: int = 6
    glitch_noise: int = 35
    flash_duration_s: float = 0.15


@dataclass(frozen=True)
class PacingConfig:
    max_visual_hold_s: float = 5.0
    max_visual_hold_short_s: float = 2.5


def load_sfx_palette(*, channel_raw_config: dict[str, Any] | None = None) -> dict[str, SfxKindConfig]:
    raw = _merged_sound_design(channel_raw_config).get("sfx_palette", {})
    defaults: dict[str, SfxKindConfig] = {
        "whoosh": SfxKindConfig(gain_db=-22.0, duration_s=0.5),
        "accent": SfxKindConfig(gain_db=-20.0, duration_s=0.6),
        "pop": SfxKindConfig(gain_db=-18.0, duration_s=0.2),
        "impact": SfxKindConfig(gain_db=-16.0, duration_s=0.4),
        "riser": SfxKindConfig(gain_db=-20.0, duration_s=1.5),
        "click": SfxKindConfig(gain_db=-22.0, duration_s=0.08),
    }
    for kind, default in defaults.items():
        block = raw.get(kind) if isinstance(raw, dict) else None
        if isinstance(block, dict):
            defaults[kind] = SfxKindConfig(
                gain_db=float(block.get("gain_db", default.gain_db)),
                duration_s=float(block.get("duration_s", default.duration_s)),
            )
    return defaults


def load_music_reveal_cut_config() -> dict[str, Any]:
    cfg = load_agent_config().get("sound_design", {}).get("music_reveal_cut", {})
    return {
        "enabled": bool(cfg.get("enabled", True)),
        "duration_ms": int(cfg.get("duration_ms", 300)),
        "depth": float(cfg.get("depth", 0.02)),
    }


def load_ambient_bed_config(*, channel_raw_config: dict[str, Any] | None = None) -> dict[str, Any]:
    cfg = _merged_sound_design(channel_raw_config).get("ambient_bed", {})
    return {
        "enabled": bool(cfg.get("enabled", False)),
        "gain_db": float(cfg.get("gain_db", -30.0)),
        "theme_presets": dict(cfg.get("theme_presets", {})),
    }


def load_texture_config(*, theme: str = "", channel_raw_config: dict[str, Any] | None = None) -> TextureConfig:
    video_cfg = _merged_video_config(channel_raw_config)
    raw = dict(video_cfg.get("texture", {}))
    by_theme = raw.pop("by_theme", {}) if isinstance(raw.get("by_theme"), dict) else {}
    theme_key = (theme or "default").lower().strip()
    if theme_key in by_theme and isinstance(by_theme[theme_key], dict):
        raw = {**raw, **by_theme[theme_key]}
    return TextureConfig(
        grain=int(raw.get("grain", 0)),
        vignette=bool(raw.get("vignette", False)),
        vignette_angle=float(raw.get("vignette_angle", 0.25)),
        light_leak=bool(raw.get("light_leak", False)),
        light_leak_opacity=float(raw.get("light_leak_opacity", 0.15)),
        vhs=bool(raw.get("vhs", False)),
        vhs_shift=int(raw.get("vhs_shift", 2)),
    )


def resolve_lut_path(theme: str) -> Path | None:
    grade_cfg = load_agent_config().get("video", {}).get("grade", {})
    lut_map = grade_cfg.get("lut_by_theme", {}) if isinstance(grade_cfg, dict) else {}
    rel = lut_map.get((theme or "").lower().strip()) or lut_map.get("default")
    if not rel:
        return None
    path = _PROJECT_ROOT / str(rel)
    return path if path.is_file() else None


def load_text_overlay_animation_config() -> TextOverlayAnimationConfig:
    raw = load_agent_config().get("text_overlays", {}).get("animation", {})
    if not isinstance(raw, dict):
        raw = {}
    by_vt = raw.get("by_visual_type", {})
    return TextOverlayAnimationConfig(
        by_visual_type=dict(by_vt) if isinstance(by_vt, dict) else {},
        highlight_color=str(raw.get("highlight_color", "#FFE600")),
        glow_intensity=float(raw.get("glow_intensity", 0.5)),
        enabled=bool(raw.get("enabled", True)),
    )


def load_impact_transition_config() -> ImpactTransitionConfig:
    raw = load_agent_config().get("video", {}).get("transitions", {}).get("impact", {})
    if not isinstance(raw, dict):
        raw = {}
    return ImpactTransitionConfig(
        glitch_frames=int(raw.get("glitch_frames", 6)),
        glitch_noise=int(raw.get("glitch_noise", 35)),
        flash_duration_s=float(raw.get("flash_duration_s", 0.15)),
    )


def load_pacing_config(*, is_short: bool = False) -> PacingConfig:
    raw = load_agent_config().get("pacing", {})
    if not isinstance(raw, dict):
        raw = {}
    if is_short:
        short_slot = (
            load_agent_config()
            .get("video", {})
            .get("short_montage_profile", {})
            .get("beat_slot_s", 2.5)
        )
        hold = float(raw.get("max_visual_hold_short_s", short_slot))
    else:
        hold = float(raw.get("max_visual_hold_s", 5.0))
    return PacingConfig(
        max_visual_hold_s=float(raw.get("max_visual_hold_s", 5.0)),
        max_visual_hold_short_s=hold,
    )


def resolve_max_visual_hold_s(*, is_short: bool = False) -> float:
    return load_pacing_config(is_short=is_short).max_visual_hold_short_s if is_short else load_pacing_config(is_short=is_short).max_visual_hold_s
