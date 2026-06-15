"""Tests musique optionnelle dans EditorAgent."""

from __future__ import annotations

from agent.agents.editor_agent import _build_mood_blocks, _scenario_requires_audio
from agent.agents.narrator_agent import segment_needs_music


def test_segment_needs_music_explicit_false() -> None:
    assert segment_needs_music({"needs_music": False, "needs_voice": True}) is False


def test_segment_needs_music_defaults_to_voice_presence() -> None:
    assert segment_needs_music({"needs_voice": True, "narration_text": "hello"}) is True
    assert segment_needs_music({"needs_voice": False}) is False


def test_build_mood_blocks_skips_segments_without_music() -> None:
    meta = {
        1: {"mood": "calme", "duration_s": 30, "needs_music": False},
        2: {"mood": "energique", "duration_s": 20, "needs_music": True},
    }
    blocks = _build_mood_blocks(meta, 50)
    assert len(blocks) == 1
    assert blocks[0]["mood"] == "energique"
    assert blocks[0]["start_s"] == 30


def test_scenario_requires_audio_false_for_silent_visual_only() -> None:
    meta = {
        1: {
            "needs_voice": False,
            "needs_music": False,
            "strip_source_audio": True,
        },
    }
    assert _scenario_requires_audio(meta) is False


def test_scenario_requires_audio_true_with_ambient() -> None:
    meta = {
        1: {
            "needs_voice": False,
            "needs_music": False,
            "strip_source_audio": False,
        },
    }
    assert _scenario_requires_audio(meta) is True
