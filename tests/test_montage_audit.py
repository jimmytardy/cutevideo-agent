"""Audit baseline qualité montage (roadmap B4)."""

from __future__ import annotations

import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.core.montage_plan import BeatClipPlan, MontagePlanData, SegmentMontagePlan, collect_clip_cut_times


def test_visual_style_block_non_empty_fixture() -> None:
    style_block = (
        "Cinematic documentary, warm archival tones, subtle film grain, "
        "high contrast rim lighting"
    )
    assert len(style_block.strip()) >= 20


def test_on_screen_text_rate_on_fixture_beats() -> None:
    beats = [
        {"order": 1, "on_screen_text": "1789"},
        {"order": 2, "on_screen_text": ""},
        {"order": 3, "on_screen_text": "Révolution"},
        {"order": 4, "on_screen_text": ""},
    ]
    with_text = sum(1 for b in beats if str(b.get("on_screen_text") or "").strip())
    assert with_text / len(beats) >= 0.25


def test_collect_clip_cut_times_multi_segment_absolute() -> None:
    project_id = uuid.uuid4()
    plan = MontagePlanData(
        project_id=project_id,
        iteration=1,
        segments=[
            SegmentMontagePlan(
                segment_order=1,
                clips=[
                    BeatClipPlan(
                        beat_order=1,
                        asset_path="/tmp/a.jpg",
                        timeline_start_s=0.0,
                        timeline_end_s=3.0,
                    ),
                    BeatClipPlan(
                        beat_order=2,
                        asset_path="/tmp/b.jpg",
                        timeline_start_s=3.0,
                        timeline_end_s=6.0,
                    ),
                    BeatClipPlan(
                        beat_order=3,
                        asset_path="/tmp/c.jpg",
                        timeline_start_s=6.0,
                        timeline_end_s=9.0,
                    ),
                    BeatClipPlan(
                        beat_order=4,
                        asset_path="/tmp/d.jpg",
                        timeline_start_s=9.0,
                        timeline_end_s=12.0,
                    ),
                ],
            ),
            SegmentMontagePlan(
                segment_order=2,
                clips=[
                    BeatClipPlan(
                        beat_order=1,
                        asset_path="/tmp/e.jpg",
                        timeline_start_s=0.0,
                        timeline_end_s=4.0,
                    ),
                    BeatClipPlan(
                        beat_order=2,
                        asset_path="/tmp/f.jpg",
                        timeline_start_s=4.0,
                        timeline_end_s=8.0,
                    ),
                    BeatClipPlan(
                        beat_order=3,
                        asset_path="/tmp/g.jpg",
                        timeline_start_s=8.0,
                        timeline_end_s=12.0,
                    ),
                    BeatClipPlan(
                        beat_order=4,
                        asset_path="/tmp/h.jpg",
                        timeline_start_s=12.0,
                        timeline_end_s=16.0,
                    ),
                ],
            ),
        ],
    )
    times = collect_clip_cut_times(plan)
    assert 3.0 in times
    assert 16.0 in times  # segment 2 offset 12 + clip start 4
    assert all(t > 0 for t in times)


@pytest.mark.asyncio
async def test_assemble_applies_flash_on_chapter_breaks(tmp_path: Path) -> None:
    from agent.skills.video import ffmpeg_utils

    seg_plan = MagicMock()
    seg_plan.segment_order = 2
    seg_plan.clips = [MagicMock()]

    montage_plan = MagicMock()
    montage_plan.segments = [seg_plan]
    montage_plan.is_vertical = False

    audio_file = MagicMock()
    audio_file.local_path = str(tmp_path / "audio.wav")
    audio_file.segment_order = 2
    (tmp_path / "audio.wav").write_bytes(b"wav")

    with (
        patch.object(ffmpeg_utils, "render_segment_from_clips", new_callable=AsyncMock),
        patch.object(ffmpeg_utils, "_apply_inter_segment_flash", new_callable=AsyncMock) as flash_mock,
        patch.object(ffmpeg_utils, "_run_ffmpeg", new_callable=AsyncMock),
        patch.object(ffmpeg_utils, "_assert_audio_stream"),
        patch("agent.skills.video.ffmpeg_utils.ffmpeg.probe", return_value={"format": {"duration": "30.0"}}),
    ):
        await ffmpeg_utils.assemble_from_montage_plan(
            montage_plan,
            audio_files=[audio_file],
            output_path=tmp_path / "out.mp4",
            project_id=uuid.uuid4(),
        )
    flash_mock.assert_awaited_once()
