"""Tests profil montage short."""

from __future__ import annotations

from agent.skills.video.montage_decisions import load_transition_config, resolve_motion_style
from agent.skills.video.montage_profile import load_ken_burns_config, short_beat_slot_s


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
