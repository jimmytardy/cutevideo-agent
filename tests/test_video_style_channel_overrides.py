"""Tests overrides Channel.config sur video_style_config (B5)."""

from __future__ import annotations

from agent.skills.video.video_style_config import (
    channel_style_overrides,
    load_ambient_bed_config,
    load_sfx_palette,
)


def test_channel_style_overrides_extracts_blocks() -> None:
    raw = {
        "video_style": {"texture": {"grain": 12}},
        "sound_design": {"ambient_bed": {"enabled": False}},
    }
    overrides = channel_style_overrides(raw)
    assert overrides["video_style"]["texture"]["grain"] == 12
    assert overrides["sound_design"]["ambient_bed"]["enabled"] is False


def test_channel_overrides_merge_ambient_bed() -> None:
    base = load_ambient_bed_config()
    assert base.get("enabled") is True
    disabled = load_ambient_bed_config(
        channel_raw_config={"sound_design": {"ambient_bed": {"enabled": False}}}
    )
    assert disabled.get("enabled") is False


def test_channel_overrides_merge_sfx_palette() -> None:
    palette = load_sfx_palette(
        channel_raw_config={"sound_design": {"sfx_palette": {"click": {"gain_db": -18.0}}}}
    )
    assert palette["click"].gain_db == -18.0
