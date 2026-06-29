"""Tests filter graph punch zoom et J/L-cuts."""

from __future__ import annotations

from agent.core.montage_plan import BeatClipPlan
from agent.skills.video.filter_graph_builder import (
    VideoProfile,
    _build_motion_vf,
    _build_narration_audio_filters,
    build_segment_filter_complex,
)


def test_punch_zoom_uses_eval_frame() -> None:
    profile = VideoProfile(width=1080, height=1920, fps=30)
    vf = _build_motion_vf("0:v", "out", 3.0, profile, "punch_zoom", is_short=True)
    assert "eval=frame" in vf
    assert "punch" not in vf  # style name not in filter
    assert "if(lt(n" in vf


def test_motion_focus_targets_face_box() -> None:
    profile = VideoProfile(width=1920, height=1080, fps=25)
    face_box = [0.3, 0.2, 0.2, 0.3]
    vf = _build_motion_vf(
        "0:v",
        "out",
        4.0,
        profile,
        "punch_zoom",
        motion_focus=face_box,
    )
    assert "(0.3+0.2/2)*in_w-out_w/2" in vf
    assert "(0.2+0.3/2)*in_h-out_h/2" in vf
    assert "(in_w-out_w)/2" not in vf


def test_narration_j_cut_delay() -> None:
    clips = [
        BeatClipPlan(
            beat_order=1,
            asset_path="/tmp/a.jpg",
            timeline_start_s=0.0,
            timeline_end_s=2.0,
        ),
        BeatClipPlan(
            beat_order=2,
            asset_path="/tmp/b.jpg",
            timeline_start_s=2.0,
            timeline_end_s=4.0,
            audio_lead_s=0.2,
        ),
    ]
    filters, label = _build_narration_audio_filters(1, clips, narration_duration_s=4.0)
    joined = ";".join(filters)
    assert "atrim=start=1.800" in joined
    assert "adelay=1800|1800" in joined
    assert label == "narrmix"


def test_build_segment_filter_complex_with_audio_lead() -> None:
    clips = [
        BeatClipPlan(
            beat_order=1,
            asset_path="/tmp/a.jpg",
            timeline_start_s=0.0,
            timeline_end_s=2.0,
        ),
        BeatClipPlan(
            beat_order=2,
            asset_path="/tmp/b.jpg",
            timeline_start_s=2.0,
            timeline_end_s=4.0,
            audio_lead_s=0.2,
        ),
    ]
    profile = VideoProfile(width=1080, height=1920, fps=30)
    _, filter_complex, _, _ = build_segment_filter_complex(
        clips,
        profile,
        is_vertical=True,
        is_short=True,
        narration_audio_path="/tmp/narration.wav",
    )
    assert "atrim=start=1.800" in filter_complex
    assert "adelay=1800|1800" in filter_complex
    assert "amix" in filter_complex
