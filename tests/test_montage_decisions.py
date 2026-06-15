from __future__ import annotations

from agent.skills.video.montage_decisions import (
    load_transition_config,
    resolve_motion_style,
    resolve_overlay_mode,
    resolve_transition,
    validate_transition,
)


def test_validate_transition_unknown_falls_back_to_fade() -> None:
    cfg = load_transition_config()
    assert validate_transition("not_a_real_transition", cfg) == "fade"


def test_resolve_transition_uses_mood_default() -> None:
    result = resolve_transition(
        segment_mood="energique",
        prev_visual_type="documentary_photo",
        next_visual_type="documentary_photo",
    )
    assert result == "wipeleft"


def test_resolve_motion_style_video_sports_static() -> None:
    assert resolve_motion_style("sports_action", "video") == "static"


def test_resolve_overlay_mode_diagram() -> None:
    assert resolve_overlay_mode("scientific_diagram") == "svg_overlay"


def test_resolve_overlay_mode_quote_drawtext() -> None:
    assert resolve_overlay_mode("quote_card") == "drawtext"
