from __future__ import annotations

import pytest

from agent.core.montage_plan import ClipMetadata, ClipSegmentMeta
from agent.skills.video.filter_graph_builder import VideoProfile, _build_motion_vf
from agent.skills.video.trim_selector import select_trim_window


def test_selects_highest_score_segment() -> None:
    meta = ClipMetadata(
        best_segments=[
            ClipSegmentMeta(
                start_s=0.0, end_s=10.0, reason="faible", score=30, peak_s=2.0,
            ),
            ClipSegmentMeta(
                start_s=10.0, end_s=20.0, reason="fort", score=80, peak_s=15.0,
            ),
        ],
    )
    sel = select_trim_window(
        source_duration_s=30.0,
        target_duration_s=4.0,
        phrase_anchor="test",
        visual_type="documentary_photo",
        clip_metadata=meta,
    )
    assert 10.0 <= sel.start_s <= 15.0 <= sel.end_s
    assert "peak@15.0s" in sel.reason
    assert "fort" in sel.reason


def test_window_centered_on_peak_s() -> None:
    meta = ClipMetadata(
        best_segments=[
            ClipSegmentMeta(
                start_s=0.0, end_s=20.0, reason="action", score=90, peak_s=5.0,
            ),
        ],
    )
    sel = select_trim_window(
        source_duration_s=30.0,
        target_duration_s=4.0,
        phrase_anchor="test",
        visual_type="documentary_photo",
        clip_metadata=meta,
    )
    assert sel.start_s == pytest.approx(3.0)
    assert sel.end_s == pytest.approx(7.0)
    assert 3.0 <= 5.0 <= 7.0


def test_clamp_left_boundary() -> None:
    meta = ClipMetadata(
        best_segments=[
            ClipSegmentMeta(
                start_s=0.0, end_s=10.0, reason="début", score=70, peak_s=0.2,
            ),
        ],
    )
    sel = select_trim_window(
        source_duration_s=30.0,
        target_duration_s=4.0,
        phrase_anchor="test",
        visual_type="documentary_photo",
        clip_metadata=meta,
    )
    assert sel.start_s == pytest.approx(0.0)
    assert sel.end_s == pytest.approx(4.0)
    assert 0.2 <= sel.end_s


def test_clamp_right_boundary() -> None:
    meta = ClipMetadata(
        best_segments=[
            ClipSegmentMeta(
                start_s=20.0, end_s=30.0, reason="fin", score=70, peak_s=29.5,
            ),
        ],
    )
    sel = select_trim_window(
        source_duration_s=30.0,
        target_duration_s=4.0,
        phrase_anchor="test",
        visual_type="documentary_photo",
        clip_metadata=meta,
    )
    assert sel.end_s == pytest.approx(30.0)
    assert sel.start_s == pytest.approx(26.0)
    assert sel.start_s <= 29.5


def test_minimum_window_duration() -> None:
    meta = ClipMetadata(
        best_segments=[
            ClipSegmentMeta(
                start_s=5.0, end_s=5.3, reason="trop court", score=90, peak_s=5.1,
            ),
        ],
    )
    sel = select_trim_window(
        source_duration_s=30.0,
        target_duration_s=6.0,
        phrase_anchor="test",
        visual_type="documentary_photo",
        clip_metadata=meta,
    )
    assert "fenêtre centrée" in sel.reason


def test_fallback_without_metadata() -> None:
    sel = select_trim_window(
        source_duration_s=30.0,
        target_duration_s=6.0,
        phrase_anchor="ancre test",
        visual_type="documentary_photo",
        clip_metadata=None,
    )
    assert sel.start_s == pytest.approx(12.0)
    assert sel.end_s == pytest.approx(18.0)
    assert "fenêtre centrée" in sel.reason


def test_establishing_shot_fallback_unchanged() -> None:
    sel = select_trim_window(
        source_duration_s=30.0,
        target_duration_s=6.0,
        phrase_anchor="test",
        visual_type="establishing_shot",
        clip_metadata=None,
    )
    assert sel.start_s == 0.0
    assert sel.end_s == pytest.approx(6.0)
    assert "establishing_shot" in sel.reason


def test_static_image_salient_crop_when_crop_box_set() -> None:
    profile = VideoProfile(width=1080, height=1920, fps=30)
    crop_box = [0.3, 0.1, 0.4, 0.8]
    vf = _build_motion_vf(
        "0:v", "out", 5.0, profile, "static", crop_box=crop_box,
    )
    assert "crop=1080:1920:x='" in vf
    assert "0.3" in vf or "0.4" in vf
    assert "(in_w-out_w)/2" in vf


def test_static_image_no_crop_box_uses_center() -> None:
    profile = VideoProfile(width=1080, height=1920, fps=30)
    vf = _build_motion_vf("0:v", "out", 5.0, profile, "static")
    assert "crop=1080:1920,fps" in vf
    assert ":x='" not in vf
