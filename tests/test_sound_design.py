"""Tests design sonore beat cuts."""

from __future__ import annotations

from agent.skills.audio.sound_design import build_beat_cut_cues, merge_sfx_cues


def test_build_beat_cut_cues_caps_per_minute() -> None:
    starts = [float(i) for i in range(20)]
    cues = build_beat_cut_cues(starts, max_per_minute=12, video_duration_s=60.0)
    assert len(cues) <= 12


def test_build_beat_cut_cues_dedupes_close_cuts() -> None:
    cues = build_beat_cut_cues([1.0, 1.1, 1.2, 5.0], max_per_minute=12)
    assert len(cues) == 2


def test_merge_sfx_cues_dedupes() -> None:
    from agent.skills.audio.sound_design import SfxCue, build_sfx_cues

    segment_cues = build_sfx_cues({1: {"duration_s": 30, "needs_voice": True}})
    beat_cues = build_beat_cut_cues([5.0, 5.1])
    merged = merge_sfx_cues(segment_cues, beat_cues)
    assert len(merged) >= 1
