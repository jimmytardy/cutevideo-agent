from __future__ import annotations

from agent.core.montage_plan import ClipMetadata
from agent.skills.video.montage_decisions import (
    resolve_motion_focus,
    resolve_motion_style,
    resolve_transition,
)

_PORTRAIT = ClipMetadata(
    composition="portrait",
    faces=1,
    face_box=[0.3, 0.2, 0.2, 0.3],
    salient_box=[0.2, 0.1, 0.5, 0.6],
    energy=50,
)

_WIDE = ClipMetadata(
    composition="wide",
    horizon_y=0.55,
    salient_box=[0.1, 0.2, 0.8, 0.5],
    energy=40,
    dominant_colors=["#1a2b3c"],
)

_DETAIL_LOW = ClipMetadata(
    composition="detail",
    energy=20,
    salient_box=[0.4, 0.4, 0.2, 0.2],
)

_DETAIL_HIGH = ClipMetadata(
    composition="detail",
    energy=75,
    salient_box=[0.4, 0.4, 0.2, 0.2],
)

_TEXT_HEAVY = ClipMetadata(
    composition="text_heavy",
    energy=30,
    dominant_colors=["#ffffff"],
)


def test_portrait_punch_zoom_with_face_focus() -> None:
    style = resolve_motion_style(
        "documentary_photo", "image", index=0, perception=_PORTRAIT
    )
    assert style == "punch_zoom"
    focus = resolve_motion_focus(_PORTRAIT, style)
    assert focus == [0.3, 0.2, 0.2, 0.3]


def test_wide_horizon_pans_not_zooms() -> None:
    style = resolve_motion_style("documentary_photo", "image", index=0, perception=_WIDE)
    assert style in ("pan_left", "pan_right")
    assert resolve_motion_focus(_WIDE, style) is None


def test_detail_low_energy_static() -> None:
    style = resolve_motion_style(
        "documentary_photo", "image", index=0, perception=_DETAIL_LOW
    )
    assert style == "static"


def test_detail_high_energy_zoom_out() -> None:
    style = resolve_motion_style(
        "documentary_photo", "image", index=0, perception=_DETAIL_HIGH
    )
    assert style == "zoom_out"


def test_high_energy_punch_zoom() -> None:
    meta = ClipMetadata(energy=80, composition="abstract")
    style = resolve_motion_style("documentary_photo", "image", index=0, perception=meta)
    assert style == "punch_zoom"


def test_perception_none_matches_legacy_cycle() -> None:
    styles = [
        resolve_motion_style("documentary_photo", "image", index=i, perception=None)
        for i in range(4)
    ]
    assert styles == ["zoom_in", "zoom_out", "pan_right", "pan_left"]


def test_motion_anti_repeat_max_two_identical() -> None:
    style = resolve_motion_style(
        "documentary_photo",
        "image",
        index=1,
        perception=_WIDE,
        last_motion="pan_right",
        motion_repeat_count=2,
    )
    assert style != "pan_right"


def test_energy_contrast_flash_impact_transition() -> None:
    prev = ClipMetadata(energy=20, composition="wide", dominant_colors=["#111111"])
    nxt = ClipMetadata(energy=80, composition="wide", dominant_colors=["#222222"])
    result = resolve_transition(
        segment_mood="calme",
        prev_visual_type="documentary_photo",
        next_visual_type="documentary_photo",
        prev_perception=prev,
        next_perception=nxt,
    )
    assert result == "flash_impact"


def test_text_heavy_sharp_transition() -> None:
    result = resolve_transition(
        segment_mood="calme",
        prev_visual_type="documentary_photo",
        next_visual_type="text_card",
        prev_perception=_WIDE,
        next_perception=_TEXT_HEAVY,
    )
    assert result == "wiperight"


def test_similar_composition_and_colors_fade() -> None:
    prev = ClipMetadata(
        composition="wide", energy=50, dominant_colors=["#aabbcc"]
    )
    nxt = ClipMetadata(
        composition="wide", energy=55, dominant_colors=["#aabbdd"]
    )
    result = resolve_transition(
        segment_mood="calme",
        prev_visual_type="documentary_photo",
        next_visual_type="documentary_photo",
        prev_perception=prev,
        next_perception=nxt,
    )
    assert result == "fade"


def test_transition_hint_still_priority() -> None:
    result = resolve_transition(
        segment_mood="calme",
        prev_visual_type="documentary_photo",
        next_visual_type="documentary_photo",
        transition_hint="glitch",
        prev_perception=_PORTRAIT,
        next_perception=_TEXT_HEAVY,
    )
    assert result == "glitch"
