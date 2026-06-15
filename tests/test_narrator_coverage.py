from __future__ import annotations

from agent.agents.narrator_agent import segment_needs_music, segment_needs_voice


def test_narrator_requires_voice_when_segments_need_it() -> None:
    segments = [
        {"order": 1, "needs_voice": True, "narration_text": "Bonjour"},
        {"order": 2, "needs_voice": False, "narration_text": ""},
    ]
    required = [s for s in segments if segment_needs_voice(s)]
    assert len(required) == 1
    assert required[0]["order"] == 1


def test_narrator_skips_empty_narration_even_if_needs_voice_true() -> None:
    assert segment_needs_voice({"needs_voice": True, "narration_text": "   "}) is False


def test_segment_needs_music_inherits_from_voice_when_unset() -> None:
    assert segment_needs_music({"needs_voice": True, "narration_text": "Bonjour"}) is True
    assert segment_needs_music({"needs_voice": False}) is False
    assert segment_needs_music({"needs_music": False, "needs_voice": True}) is False


def test_narrator_voice_required_count_zero_when_all_silent() -> None:
    segments = [
        {"order": 1, "needs_voice": False, "narration_text": ""},
        {"order": 2, "needs_voice": True, "narration_text": ""},
    ]
    assert len([s for s in segments if segment_needs_voice(s)]) == 0
