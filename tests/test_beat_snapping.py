"""Tests snapping musical des frontières de plan."""

from __future__ import annotations

from agent.core.montage_plan import BeatClipPlan
from agent.skills.video.beat_snap import (
    measure_beat_alignment,
    snap_clip_boundaries,
    snap_time_to_nearest_beat,
)


def _clip(order: int, start: float, end: float) -> BeatClipPlan:
    return BeatClipPlan(
        beat_order=order,
        asset_path=f"/tmp/{order}.jpg",
        timeline_start_s=start,
        timeline_end_s=end,
    )


def test_snap_time_within_tolerance() -> None:
    beats = [0.0, 0.5, 1.0, 1.5, 2.0]
    assert snap_time_to_nearest_beat(1.08, beats, tolerance_s=0.15) == 1.0
    assert snap_time_to_nearest_beat(1.08, beats, tolerance_s=0.05) == 1.08


def test_snap_clip_boundaries_preserves_continuity() -> None:
    clips = [
        _clip(1, 0.0, 1.02),
        _clip(2, 1.02, 2.05),
        _clip(3, 2.05, 3.0),
        _clip(4, 3.0, 4.0),
    ]
    beats = [0.0, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0]
    snapped = snap_clip_boundaries(
        clips, beats, tolerance_s=0.15, audio_duration_s=4.0
    )
    for i in range(1, len(snapped)):
        assert snapped[i].timeline_start_s == snapped[i - 1].timeline_end_s
    assert snapped[-1].timeline_end_s == 4.0


def test_snap_respects_tolerance_no_drift() -> None:
    clips = [
        _clip(1, 0.0, 2.0),
        _clip(2, 2.0, 4.0),
    ]
    beats = [0.0, 3.0]
    snapped = snap_clip_boundaries(
        clips, beats, tolerance_s=0.15, audio_duration_s=4.0
    )
    assert snapped[1].timeline_start_s == 2.0


def test_measure_beat_alignment_ratio() -> None:
    cuts = [1.0, 2.0, 3.0, 3.8]
    beats = [0.0, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0]
    ratio = measure_beat_alignment(cuts, beats, tolerance_s=0.15)
    assert ratio >= 0.75


def test_snap_high_alignment_fixture() -> None:
    """≥ 70 % des coupes alignées sur beats réguliers."""
    beats = [i * 0.5 for i in range(20)]
    clips = [
        _clip(1, 0.0, 1.03),
        _clip(2, 1.03, 2.07),
        _clip(3, 2.07, 3.02),
        _clip(4, 3.02, 4.05),
        _clip(5, 4.05, 5.0),
    ]
    snapped = snap_clip_boundaries(
        clips, beats, tolerance_s=0.15, audio_duration_s=5.0
    )
    cut_times = [c.timeline_start_s for c in snapped[1:]]
    ratio = measure_beat_alignment(cut_times, beats, tolerance_s=0.15)
    assert ratio >= 0.7
