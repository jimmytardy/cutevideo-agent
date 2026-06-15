from __future__ import annotations

from agent.core.montage_plan import BeatClipPlan
from agent.skills.video.filter_graph_builder import (
    build_segment_filter_complex,
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
    input_args, filter_complex, vout = build_segment_filter_complex(
        [clip], profile, is_vertical=False,
    )
    assert "-loop" in input_args
    assert "xfade" not in filter_complex
    assert vout == "vout"
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
    _, filter_complex, _ = build_segment_filter_complex(
        clips, profile, is_vertical=False,
    )
    assert "xfade=transition=dissolve" in filter_complex

