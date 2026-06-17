from __future__ import annotations

from agent.agents.outline_agent import _sanitize_outline
from agent.agents.scenario_agent import _format_outline_block


def test_sanitize_outline_normalizes_segments_and_fills_defaults() -> None:
    raw = {
        "title": "Mon titre",
        "segments": [
            {"title": "Hook", "duration_s": 15, "mood": "energique", "intent": "accroche"},
            {"order": 2, "title": "Coeur", "needs_voice": False},
        ],
    }
    out = _sanitize_outline(raw, target_duration_s=120)
    assert out["title"] == "Mon titre"
    assert out["total_duration_s"] == 120
    assert len(out["segments"]) == 2
    first = out["segments"][0]
    assert first["order"] == 1
    assert first["needs_voice"] is True
    assert first["mood"] == "energique"
    assert first["intent"] == "accroche"
    second = out["segments"][1]
    assert second["order"] == 2
    assert second["needs_voice"] is False


def test_sanitize_outline_skips_non_dict_segments() -> None:
    out = _sanitize_outline({"segments": ["bad", {"title": "ok"}]}, target_duration_s=60)
    assert len(out["segments"]) == 1
    assert out["segments"][0]["title"] == "ok"


def test_format_outline_block_includes_titles_and_intent() -> None:
    outline = {
        "segments": [
            {
                "order": 1,
                "title": "Le paradoxe",
                "duration_s": 150,
                "needs_voice": True,
                "needs_music": True,
                "mood": "inspirant",
                "hook_type": "question",
                "intent": "poser le paradoxe central",
            }
        ]
    }
    block = _format_outline_block(outline)
    assert "Le paradoxe" in block
    assert "poser le paradoxe central" in block
    assert "mood=inspirant" in block
    assert "hook=question" in block


def test_format_outline_block_marks_voiceless_segment() -> None:
    outline = {"segments": [{"order": 1, "title": "Visuel", "needs_voice": False, "needs_music": False}]}
    block = _format_outline_block(outline)
    assert "SANS voix" in block
    assert "sans musique" in block
