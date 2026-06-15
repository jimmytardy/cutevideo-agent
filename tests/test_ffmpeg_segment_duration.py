from __future__ import annotations

from agent.skills.video.montage_decisions import (
    compute_xfade_offset,
    total_visual_duration,
)


def test_transition_overlap_single_clip() -> None:
    assert total_visual_duration([5.0], 0.4, True) == 5.0


def test_transition_overlap_multiple_clips() -> None:
    durations = [4.0, 4.0, 4.0]
    overlap = total_visual_duration(durations, 0.4, True)
    assert overlap < sum(durations)


def test_compute_xfade_offset_positive() -> None:
    offset = compute_xfade_offset([6.0, 5.0], 0, 0.4)
    assert offset == 5.6
