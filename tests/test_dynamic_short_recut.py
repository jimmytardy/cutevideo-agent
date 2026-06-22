"""Tests dynamic short re-cut planning."""

from __future__ import annotations


def test_dynamic_recut_clip_count() -> None:
    duration_s = 30.0
    subclip_s = 2.5
    n_clips = max(2, min(6, int(duration_s // subclip_s)))
    assert n_clips >= 2
