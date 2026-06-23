"""Tests design sonore beat cuts."""

from __future__ import annotations

import uuid

from agent.core.montage_plan import BeatClipPlan, MontagePlanData, SegmentMontagePlan
from agent.skills.audio.sound_design import (
    build_beat_cut_cues,
    build_motion_cues,
    build_transition_cues,
    merge_sfx_cues,
)


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


def test_long_profile_beat_cap() -> None:
    starts = [float(i) for i in range(30)]
    cues = build_beat_cut_cues(starts, max_per_minute=10, video_duration_s=60.0)
    assert len(cues) <= 10


def test_transition_cues_on_circleopen() -> None:
    plan = MontagePlanData(
        project_id=uuid.uuid4(),
        iteration=1,
        segments=[
            SegmentMontagePlan(
                segment_order=1,
                clips=[
                    BeatClipPlan(
                        beat_order=1,
                        asset_path="/tmp/a.jpg",
                        timeline_start_s=0.0,
                        timeline_end_s=4.0,
                        transition_out="circleopen",
                        transition_duration_s=0.4,
                    ),
                    BeatClipPlan(
                        beat_order=2,
                        asset_path="/tmp/b.jpg",
                        timeline_start_s=4.0,
                        timeline_end_s=8.0,
                    ),
                ],
            )
        ],
    )
    cues = build_transition_cues(plan)
    assert len(cues) == 1
    assert cues[0].kind == "click"


def test_motion_cues_on_punch_zoom() -> None:
    plan = MontagePlanData(
        project_id=uuid.uuid4(),
        iteration=1,
        segments=[
            SegmentMontagePlan(
                segment_order=1,
                clips=[
                    BeatClipPlan(
                        beat_order=1,
                        asset_path="/tmp/a.jpg",
                        timeline_start_s=0.0,
                        timeline_end_s=4.0,
                        motion_style="punch_zoom",
                    ),
                ],
            )
        ],
    )
    cues = build_motion_cues(plan)
    assert len(cues) == 1
    assert cues[0].kind == "impact"

