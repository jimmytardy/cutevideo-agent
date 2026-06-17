from __future__ import annotations

from agent.core.montage_plan import BeatClipPlan
from agent.skills.video.filter_graph_builder import (
    build_segment_filter_complex,
    color_grade_from_style_block,
    profile_from_config,
)
from agent.skills.video.montage_decisions import (
    clip_duration_s,
    compute_xfade_offset,
    total_visual_duration,
)


def test_compute_xfade_offset_first_transition() -> None:
    durations = [5.0, 4.0]
    offset = compute_xfade_offset(durations, 0, 0.4)
    assert offset == 4.6


def test_compute_xfade_offset_second_transition() -> None:
    durations = [5.0, 4.0, 3.0]
    offset = compute_xfade_offset(durations, 1, 0.4)
    assert offset == 8.2


def test_total_visual_duration_with_transitions() -> None:
    durations = [5.0, 4.0, 3.0]
    total = total_visual_duration(durations, 0.4, True)
    assert total == 11.2


def test_build_filter_complex_single_image_clip() -> None:
    clip = BeatClipPlan(
        beat_order=1,
        asset_path="/tmp/image.jpg",
        asset_type="image",
        timeline_start_s=0.0,
        timeline_end_s=5.0,
        motion_style="zoom_in",
    )
    profile = profile_from_config(is_vertical=False)
    input_args, filter_complex, vout, aout = build_segment_filter_complex(
        [clip], profile, is_vertical=False,
    )
    assert "-loop" in input_args
    assert "eval=frame" in filter_complex
    assert "on/" not in filter_complex
    assert "xfade" not in filter_complex
    assert vout == "vout"
    assert aout == "aout"
    assert clip_duration_s(clip) == 5.0


def test_build_filter_complex_chains_xfade() -> None:
    clips = [
        BeatClipPlan(
            beat_order=1,
            asset_path="/tmp/a.jpg",
            asset_type="image",
            timeline_start_s=0.0,
            timeline_end_s=4.0,
            transition_out="dissolve",
        ),
        BeatClipPlan(
            beat_order=2,
            asset_path="/tmp/b.jpg",
            asset_type="image",
            timeline_start_s=4.0,
            timeline_end_s=8.0,
        ),
    ]
    profile = profile_from_config(is_vertical=False)
    _, filter_complex, _, _ = build_segment_filter_complex(
        clips, profile, is_vertical=False,
    )
    assert "xfade=transition=dissolve" in filter_complex


def test_color_grade_warm_palette() -> None:
    grade = color_grade_from_style_block(
        "cohesive archival documentary look, warm sepia and amber palette"
    )
    assert "colorbalance=rm=0.05" in grade
    assert "eq=saturation" in grade


def test_color_grade_cool_desaturated_noir() -> None:
    grade = color_grade_from_style_block(
        "cohesive noir documentary look, desaturated cold palette, low-key chiaroscuro"
    )
    assert "colorbalance=rm=-0.04" in grade
    assert "saturation=0.85" in grade


def test_color_grade_vivid() -> None:
    grade = color_grade_from_style_block("cohesive playful look, vivid saturated palette")
    assert "saturation=1.12" in grade


def test_color_grade_empty_style_is_neutral() -> None:
    assert color_grade_from_style_block("") == ""
    assert color_grade_from_style_block("   ") == ""


def test_grade_applied_to_video_output() -> None:
    clip = BeatClipPlan(
        beat_order=1,
        asset_path="/tmp/image.jpg",
        asset_type="image",
        timeline_start_s=0.0,
        timeline_end_s=5.0,
        motion_style="zoom_in",
    )
    profile = profile_from_config(is_vertical=False)
    grade = "eq=saturation=1.12:contrast=1.04"
    _, filter_complex, vout, _ = build_segment_filter_complex(
        [clip], profile, is_vertical=False, grade=grade,
    )
    assert grade in filter_complex
    assert f"[{vout}]" in filter_complex
    assert vout == "vgr"


def test_no_grade_keeps_default_output_label() -> None:
    clip = BeatClipPlan(
        beat_order=1,
        asset_path="/tmp/image.jpg",
        asset_type="image",
        timeline_start_s=0.0,
        timeline_end_s=5.0,
        motion_style="zoom_in",
    )
    profile = profile_from_config(is_vertical=False)
    _, _, vout, _ = build_segment_filter_complex([clip], profile, is_vertical=False)
    assert vout == "vout"


def test_build_filter_complex_ambient_audio_with_narration() -> None:
    clip = BeatClipPlan(
        beat_order=1,
        asset_path="/tmp/clip.mp4",
        asset_type="video",
        timeline_start_s=0.0,
        timeline_end_s=6.0,
        strip_source_audio=False,
        source_trim_start_s=1.0,
    )
    profile = profile_from_config(is_vertical=True)
    _, filter_complex, _, _ = build_segment_filter_complex(
        [clip],
        profile,
        is_vertical=True,
        narration_audio_path="/tmp/narration.wav",
    )
    assert "atrim" in filter_complex
    assert "amix" in filter_complex

