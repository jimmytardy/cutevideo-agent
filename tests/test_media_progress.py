"""Tests calcul de progression Media Agent."""

from __future__ import annotations

from agent.skills.media.progress import (
    build_media_progress,
    compute_expected_media_total,
)


def _segments(count: int) -> list[dict]:
    return [{"order": i, "title": f"Seg {i}"} for i in range(1, count + 1)]


def test_expected_total_classic_segments() -> None:
    total, segments_total = compute_expected_media_total(
        _segments(10),
        visual_beats_enabled=False,
        images_per_segment=4,
    )
    assert total == 40
    assert segments_total == 10


def test_expected_total_visual_beats() -> None:
    segments = [
        {
            "order": 1,
            "visual_beats": [
                {"order": 1, "phrase_anchor": "a", "visual_type": "documentary_photo", "prompt": "a"},
                {"order": 2, "phrase_anchor": "b", "visual_type": "documentary_photo", "prompt": "b"},
                {"order": 3, "phrase_anchor": "c", "visual_type": "documentary_photo", "prompt": "c"},
            ],
        },
        {"order": 2, "title": "Sans beats"},
    ]
    total, segments_total = compute_expected_media_total(
        segments,
        visual_beats_enabled=True,
        images_per_segment=4,
    )
    assert total == 7
    assert segments_total == 2


def test_build_media_progress_percent() -> None:
    progress = build_media_progress(
        iteration=1,
        found=8,
        total=40,
        segments_done=2,
        segments_total=10,
        agent_status="running",
    )
    assert progress.found == 8
    assert progress.total == 40
    assert progress.percent == 20
    assert progress.agent_status == "running"


def test_build_media_progress_zero_total() -> None:
    progress = build_media_progress(
        iteration=2,
        found=0,
        total=0,
        segments_done=0,
        segments_total=0,
        agent_status="pending",
    )
    assert progress.percent == 0
    assert progress.iteration == 2
