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


def test_resolve_motion_style_alternates_for_photos() -> None:
    # Les photos consécutives ne doivent plus toutes faire zoom_in.
    styles = [
        resolve_motion_style("documentary_photo", "image", index=i) for i in range(4)
    ]
    assert styles == ["zoom_in", "zoom_out", "pan_right", "pan_left"]
    # Le cycle se répète.
    assert resolve_motion_style("documentary_photo", "image", index=4) == "zoom_in"


def test_resolve_motion_style_hint_overrides_alternation() -> None:
    assert (
        resolve_motion_style("documentary_photo", "image", motion_hint="static", index=2)
        == "static"
    )


def test_resolve_motion_style_diagram_stays_zoom_in() -> None:
    assert resolve_motion_style("scientific_diagram", "image", index=3) == "zoom_in"


def test_resolve_overlay_mode_diagram() -> None:
    assert resolve_overlay_mode("scientific_diagram") == "svg_overlay"


def test_resolve_overlay_mode_quote_drawtext() -> None:
    assert resolve_overlay_mode("quote_card") == "drawtext"


def test_resolve_overlay_mode_photo_with_text_is_drawtext() -> None:
    # Appui-texte sur une photo réelle : déclenché par on_screen_text, pas par le type.
    assert resolve_overlay_mode("documentary_photo", "1889") == "drawtext"


def test_resolve_overlay_mode_photo_without_text_is_none() -> None:
    assert resolve_overlay_mode("documentary_photo", "") == "none"
    assert resolve_overlay_mode("documentary_photo", "   ") == "none"
