from __future__ import annotations

import pytest

from agent.core.montage_plan import BeatClipPlan
from agent.skills.video.clip_timeline_normalize import (
    TimelineClipDraft,
    expand_timeline_to_clip_drafts,
    extend_last_clip_to_match_audio,
    split_beat_duration,
    validate_visual_audio_alignment,
)


def test_split_beat_duration_under_max() -> None:
    chunks = split_beat_duration(0.0, 5.0, max_shot_s=8.0)
    assert chunks == [(0.0, 5.0)]


def test_split_beat_duration_long_beat() -> None:
    chunks = split_beat_duration(10.0, 15.0, max_shot_s=8.0)
    assert len(chunks) == 2
    assert chunks[0] == (10.0, 18.0)
    assert chunks[1] == (18.0, 25.0)
    assert sum(end - start for start, end in chunks) == pytest.approx(15.0)


def test_expand_timeline_splits_long_beat() -> None:
    drafts = [
        TimelineClipDraft(
            beat_order=1,
            source_beat_orders=[1],
            asset_path="/tmp/a.jpg",
            asset_type="image",
            timeline_start_s=0.0,
            timeline_end_s=15.0,
        )
    ]
    expanded = expand_timeline_to_clip_drafts(drafts, max_static_shot_s=8.0)
    assert len(expanded) == 2
    assert expanded[0].timeline_end_s - expanded[0].timeline_start_s == pytest.approx(8.0)
    assert expanded[1].timeline_end_s - expanded[1].timeline_start_s == pytest.approx(7.0)


def test_extend_last_clip_to_match_audio() -> None:
    clips = [
        BeatClipPlan(
            beat_order=1,
            asset_path="/tmp/a.jpg",
            asset_type="image",
            timeline_start_s=0.0,
            timeline_end_s=9.0,
        )
    ]
    updated = extend_last_clip_to_match_audio(clips, audio_duration_s=10.0)
    assert updated[-1].timeline_end_s == pytest.approx(10.0)


def test_validate_visual_audio_alignment_ok() -> None:
    clips = [
        BeatClipPlan(
            beat_order=1,
            asset_path="/tmp/a.jpg",
            asset_type="image",
            timeline_start_s=0.0,
            timeline_end_s=10.0,
        )
    ]
    validate_visual_audio_alignment(clips, 10.0)


def test_validate_visual_audio_alignment_raises() -> None:
    clips = [
        BeatClipPlan(
            beat_order=1,
            asset_path="/tmp/a.jpg",
            asset_type="image",
            timeline_start_s=0.0,
            timeline_end_s=5.0,
        )
    ]
    with pytest.raises(RuntimeError, match="Désalignement montage"):
        validate_visual_audio_alignment(clips, 12.0, tolerance_s=0.5)
