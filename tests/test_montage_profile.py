"""Tests profil montage short et long."""

from __future__ import annotations

from unittest.mock import MagicMock

from agent.skills.video.montage_decisions import load_transition_config, resolve_motion_style
from agent.skills.video.montage_profile import (
    inter_segment_flash_config,
    load_ken_burns_config,
    load_sfx_config,
    long_sfx_config,
    short_beat_slot_s,
)


def test_short_transition_duration_is_faster() -> None:
    long_cfg = load_transition_config(is_short=False)
    short_cfg = load_transition_config(is_short=True)
    assert short_cfg.duration_s <= long_cfg.duration_s
    assert short_cfg.duration_s <= 0.25


def test_short_ken_burns_stronger_zoom() -> None:
    long_kb = load_ken_burns_config(is_short=False)
    short_kb = load_ken_burns_config(is_short=True)
    assert float(short_kb["zoom_factor"]) > float(long_kb["zoom_factor"])
    assert short_kb["pan_enabled"] is True


def test_short_beat_slot() -> None:
    assert short_beat_slot_s() == 2.5


def test_resolve_motion_style_accepts_punch_zoom() -> None:
    assert resolve_motion_style("documentary_photo", "image", motion_hint="punch_zoom") == "punch_zoom"


def test_short_photo_not_static() -> None:
    style = resolve_motion_style("documentary_photo", "image", index=1, is_short=True)
    assert style != "static"


def test_long_sfx_config_enables_beat_cuts() -> None:
    cfg = long_sfx_config()
    assert cfg.get("beat_cuts_enabled") is True
    assert int(cfg.get("max_cues_per_minute", 0)) == 10


def test_load_sfx_config_long_vs_short() -> None:
    long_ctx = MagicMock()
    long_ctx.is_short_project = False
    long_ctx.derivation_short_index = None
    short_ctx = MagicMock()
    short_ctx.is_short_project = True
    short_ctx.derivation_short_index = None

    long_cfg = load_sfx_config(long_ctx)
    short_cfg = load_sfx_config(short_ctx)
    assert long_cfg.get("beat_cuts_enabled") is True
    assert short_cfg.get("beat_cuts_enabled") is True
    assert int(long_cfg.get("max_cues_per_minute", 0)) == 10
    assert int(short_cfg.get("max_cues_per_minute", 0)) == 12


def test_inter_segment_flash_long_only() -> None:
    enabled, duration = inter_segment_flash_config(is_short=False)
    assert enabled is True
    assert duration == 0.15
    assert inter_segment_flash_config(is_short=True) == (False, 0.0)
