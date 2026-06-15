from __future__ import annotations

from agent.skills.video.ffmpeg_utils import (
    _transition_overlap_duration,
    _video_pad_filter_suffix,
)


def test_transition_overlap_single_clip() -> None:
    assert _transition_overlap_duration(1) == 0.0


def test_transition_overlap_multiple_clips() -> None:
    overlap = _transition_overlap_duration(4)
    assert overlap > 0.0


def test_video_pad_filter_suffix_zero() -> None:
    assert _video_pad_filter_suffix(0.0) == ""


def test_video_pad_filter_suffix_positive() -> None:
    assert "tpad=stop_mode=clone" in _video_pad_filter_suffix(1.5)
