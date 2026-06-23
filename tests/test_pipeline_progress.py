"""Tests calcul de progression pipeline par agent."""

from __future__ import annotations

from agent.skills.media.progress import MediaProgressData, build_media_progress
from agent.skills.pipeline_progress.rules import (
    build_progress,
    compute_binary_progress,
    compute_hook_progress,
    compute_media_agent_progress,
    compute_montage_progress,
    compute_narrator_progress,
    compute_outline_progress,
    compute_research_progress,
    compute_scenario_progress,
    compute_short_editor_progress,
    count_voice_segments,
)


def test_build_progress_percent_clamped() -> None:
    progress = build_progress(8, 40)
    assert progress.percent == 20
    assert progress.done == 8
    assert progress.total == 40

    full = build_progress(50, 40)
    assert full.percent == 100


def test_build_progress_zero_total() -> None:
    progress = build_progress(0, 0)
    assert progress.percent == 0


def test_research_progress_empty() -> None:
    progress = compute_research_progress(None)
    assert progress.done == 0
    assert progress.total == 6
    assert progress.percent == 0


def test_research_progress_skipped() -> None:
    progress = compute_research_progress({"confidence": 0.0, "key_facts": []})
    assert progress.percent == 100
    assert progress.detail == "Ignoré"


def test_research_progress_partial() -> None:
    progress = compute_research_progress({
        "confidence": 0.8,
        "key_facts": ["fait 1"],
        "sources": [{"title": "src"}],
    })
    assert progress.done == 2
    assert progress.total == 6
    assert progress.percent == 33


def test_scenario_progress() -> None:
    empty = compute_scenario_progress([])
    assert empty.percent == 0
    done = compute_scenario_progress([{"order": 1, "narration_text": "hello"}])
    assert done.percent == 100


def test_hook_progress() -> None:
    empty = compute_hook_progress(None)
    assert empty.done == 0
    assert empty.total == 4

    hook = {
        "order": 1,
        "narration_text": "Saviez-vous que…",
        "delivery_style": {"pace": "fast"},
        "search_keywords": ["kw"],
    }
    partial = compute_hook_progress(hook)
    assert partial.done == 3
    assert partial.percent == 75


def test_count_voice_segments() -> None:
    segments = [
        {"order": 1, "narration_text": "Voix"},
        {"order": 2, "narration_text": ""},
        {"order": 3, "needs_voice": False, "narration_text": "skip"},
    ]
    assert count_voice_segments(segments) == 1


def test_narrator_progress() -> None:
    progress = compute_narrator_progress(3, 10)
    assert progress.done == 3
    assert progress.total == 10
    assert progress.percent == 30
    assert progress.detail == "3/10 voix"


def test_montage_progress() -> None:
    progress = compute_montage_progress(4, 10)
    assert progress.percent == 40
    assert progress.detail == "4/10 segments"


def test_media_agent_progress_mapping() -> None:
    media = build_media_progress(
        iteration=1,
        found=12,
        total=40,
        segments_done=3,
        segments_total=10,
        agent_status="running",
    )
    item = compute_media_agent_progress(media)
    assert item.done == 12
    assert item.total == 40
    assert item.percent == 30
    assert item.segments_done == 3
    assert item.segments_total == 10
    assert item.detail == "12/40 médias"


def test_binary_progress() -> None:
    assert compute_binary_progress(False).percent == 0
    assert compute_binary_progress(True).percent == 100


def test_outline_progress() -> None:
    empty = compute_outline_progress(None)
    assert empty.percent == 0
    done = compute_outline_progress({"segments": [{"order": 1}, {"order": 2}]})
    assert done.percent == 100
    assert done.detail == "2 segments plan"


def test_short_editor_progress() -> None:
    progress = compute_short_editor_progress(6, 15)
    assert progress.percent == 40
    assert progress.detail == "6/15 exports"

    empty = compute_short_editor_progress(0, 0)
    assert empty.total == 0
    assert empty.percent == 0
