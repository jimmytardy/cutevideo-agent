"""Tests socle style YouTubers — sound_design, animated_text, filter_graph, montage."""

from __future__ import annotations

import uuid

from agent.core.montage_plan import BeatClipPlan, MontagePlanData, SegmentMontagePlan
from agent.skills.audio.sound_design import (
    SfxCue,
    _shape_filter,
    _synth_input,
    build_overlay_cues,
    merge_sfx_cues,
)
from agent.skills.video.animated_text import (
    TextOverlayEvent,
    build_animated_overlay_ass,
    parse_animation_styles,
)
from agent.skills.video.filter_graph_builder import (
    build_source_pregrade_vf,
    build_texture_vf,
    color_grade_from_style_block,
)
from agent.skills.video.montage_decisions import (
    resolve_motion_style,
    resolve_text_animation,
    resolve_transition,
)
from agent.skills.video.video_style_config import load_text_overlay_animation_config


def test_synth_input_supports_new_kinds() -> None:
    for kind in ("pop", "impact", "riser", "whoosh", "accent"):
        source, dur = _synth_input(kind)
        assert dur > 0
        assert source


def test_shape_filter_supports_new_kinds() -> None:
    for kind in ("pop", "impact", "riser"):
        shaped = _shape_filter(kind, -18.0, 100)
        assert "adelay=100|100" in shaped
        assert "aformat=channel_layouts=stereo" in shaped


def test_build_overlay_cues_places_pop_and_impact() -> None:
    plan = MontagePlanData(
        project_id=uuid.uuid4(),
        iteration=1,
        segments=[
            SegmentMontagePlan(
                segment_order=1,
                clips=[
                    BeatClipPlan(
                        beat_order=1,
                        asset_path="/tmp/a.jpg",
                        timeline_start_s=0.0,
                        timeline_end_s=3.0,
                        on_screen_text="42 %",
                        overlay_mode="ass_overlay",
                        visual_type="statistic_highlight",
                    )
                ],
            )
        ],
    )
    cues = build_overlay_cues(plan)
    kinds = {c.kind for c in cues}
    assert "pop" in kinds
    assert "impact" in kinds
    assert cues[0].time_s == 0.0


def test_animated_ass_pop_bounce_and_highlight() -> None:
    cfg = load_text_overlay_animation_config()
    ass = build_animated_overlay_ass(
        [
            TextOverlayEvent(
                start_s=1.0,
                end_s=3.0,
                text="En 1789, 80 %",
                animation="pop_bounce+highlight",
                visual_type="statistic_highlight",
            )
        ],
        cfg,
        play_res_x=1920,
        play_res_y=1080,
    )
    assert "[Script Info]" in ass
    assert "Dialogue:" in ass
    assert "1789" in ass or "80" in ass
    assert parse_animation_styles("pop_bounce+highlight") == ["pop_bounce", "highlight"]


def test_color_grade_includes_lut_for_theme() -> None:
    grade = color_grade_from_style_block("", theme="histoire")
    assert "lut3d=" in grade


def test_texture_vf_contains_grain_when_enabled() -> None:
    vf = build_texture_vf(theme="histoire", clip_index=0)
    assert "noise=alls=" in vf


def test_archival_pregrade() -> None:
    assert "noise=alls=" in build_source_pregrade_vf("archival_footage")


def test_resolve_text_animation_statistic_highlight() -> None:
    assert "highlight" in resolve_text_animation("statistic_highlight")


def test_resolve_motion_style_statistic_highlight_punch() -> None:
    assert resolve_motion_style("statistic_highlight", "image", index=0) == "punch_zoom"


def test_resolve_transition_chapter_break_flash_impact() -> None:
    result = resolve_transition(
        segment_mood="calme",
        prev_visual_type="documentary_photo",
        next_visual_type="statistic_highlight",
        is_chapter_break=True,
        hook_type="chiffre",
    )
    assert result == "flash_impact"


def test_merge_sfx_cues_keeps_distinct_kinds_at_same_time() -> None:
    merged = merge_sfx_cues(
        [SfxCue(1.0, "pop", -18.0)],
        [SfxCue(1.05, "impact", -16.0)],
    )
    assert len(merged) == 2
