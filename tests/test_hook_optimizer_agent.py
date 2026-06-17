"""Tests for hook_optimizer_agent JSON merge helpers."""

from __future__ import annotations

from agent.agents.hook_optimizer_agent import (
    HOOK_OPTIMIZABLE_KEYS,
    HookOptimizerAgent,
    _extract_hook_subset,
    _merge_hook,
)
from agent.core.scenario_integrity import validate_segment_count_preserved


def test_extract_hook_subset_ignores_media_validation() -> None:
    hook = {
        "order": 1,
        "title": "Hook",
        "narration_text": "Saviez-vous que…",
        "media_validation": {"subject_entity": "Tour de Pise", "segments": {"1": {}}},
    }
    subset = _extract_hook_subset(hook)
    assert "media_validation" not in subset
    assert subset["narration_text"] == "Saviez-vous que…"


def test_merge_hook_strips_visual_beats_for_voice() -> None:
    segment = {
        "order": 1,
        "needs_voice": True,
        "narration_text": "Ancien texte",
        "visual_beats": [{"order": 1, "phrase_anchor": "Ancien"}],
        "media_validation": {"subject_entity": "Tour de Pise"},
    }
    optimized = {
        "narration_text": "Nouveau texte accrocheur ?",
        "visual_beats": [{"order": 1, "phrase_anchor": "Nouveau"}],
        "delivery_style": {"pace": "fast"},
        "media_validation": {"subject_entity": "Corrompu"},
    }
    merged = _merge_hook(segment, optimized)
    assert merged["narration_text"] == "Nouveau texte accrocheur ?"
    assert "visual_beats" not in merged
    assert merged["media_validation"] == {"subject_entity": "Tour de Pise"}
    assert merged["order"] == 1


def test_parse_json_accepts_markdown_block() -> None:
    raw = """```json
{
  "narration_text": "Question rhétorique ?",
  "delivery_style": {"pace": "fast"}
}
```"""
    data = HookOptimizerAgent._parse_json(raw)
    assert data["narration_text"] == "Question rhétorique ?"
    assert "visual_beats" not in data


def test_optimizable_keys_exclude_visual_beats() -> None:
    assert "narration_text" in HOOK_OPTIMIZABLE_KEYS
    assert "visual_beats" not in HOOK_OPTIMIZABLE_KEYS
    assert "media_validation" not in HOOK_OPTIMIZABLE_KEYS


def test_merge_hook_preserves_multi_segment_scenario() -> None:
    segments = [
        {
            "order": 1,
            "title": "Hook",
            "needs_voice": True,
            "narration_text": "Ancien hook",
            "visual_beats": [{"order": 1, "phrase_anchor": "Ancien"}],
        },
        {
            "order": 2,
            "title": "Développement",
            "narration_text": "Corps du segment 2",
            "needs_voice": True,
            "visual_beats": [{"order": 1, "phrase_anchor": "Corps"}],
        },
    ]
    optimized = {
        "narration_text": "Nouveau hook accrocheur ?",
        "visual_beats": [{"order": 1, "phrase_anchor": "Nouveau"}],
        "delivery_style": {"pace": "fast"},
    }
    new_segments: list[dict] = []
    for seg in segments:
        if int(seg.get("order", 0)) == 1:
            new_segments.append(_merge_hook(seg, optimized))
        else:
            new_segments.append(seg)

    validate_segment_count_preserved(segments, new_segments, context="hook_optimizer_agent")
    assert new_segments[0]["narration_text"] == "Nouveau hook accrocheur ?"
    assert "visual_beats" not in new_segments[0]
    assert new_segments[1]["narration_text"] == "Corps du segment 2"
    assert new_segments[1]["title"] == "Développement"
