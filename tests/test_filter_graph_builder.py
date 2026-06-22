"""Tests filter graph punch zoom."""

from __future__ import annotations

from agent.skills.video.filter_graph_builder import VideoProfile, _build_motion_vf


def test_punch_zoom_uses_eval_frame() -> None:
    profile = VideoProfile(width=1080, height=1920, fps=30)
    vf = _build_motion_vf("0:v", "out", 3.0, profile, "punch_zoom", is_short=True)
    assert "eval=frame" in vf
    assert "punch" not in vf  # style name not in filter
    assert "if(lt(n" in vf
