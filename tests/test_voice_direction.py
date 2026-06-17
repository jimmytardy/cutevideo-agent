from __future__ import annotations

from agent.skills.audio.ssml_builder import VALID_AZURE_STYLES
from agent.skills.audio.voice_direction import direct_voice_for_revision


def test_flat_style_becomes_expressive() -> None:
    flat = {"pace": "normal", "emotion": "serious", "azure_style": "narration-relaxed"}
    out = direct_voice_for_revision(flat, segment_index=0, iteration=1, mood="")
    assert out["azure_style"] != "narration-relaxed"
    assert out["azure_style"] in VALID_AZURE_STYLES


def test_emphasis_words_preserved() -> None:
    out = direct_voice_for_revision(
        {"emphasis_words": ["incroyable", "jamais"]}, segment_index=0, iteration=1
    )
    assert out["emphasis_words"] == ["incroyable", "jamais"]


def test_adjacent_segments_differ() -> None:
    a = direct_voice_for_revision({}, segment_index=0, iteration=1, mood="")
    b = direct_voice_for_revision({}, segment_index=1, iteration=1, mood="")
    assert (a["azure_style"], a["emotion"]) != (b["azure_style"], b["emotion"])


def test_iterations_differ_for_same_segment() -> None:
    first = direct_voice_for_revision({}, segment_index=0, iteration=1, mood="")
    second = direct_voice_for_revision({}, segment_index=0, iteration=2, mood="")
    assert first != second


def test_dark_mood_uses_grave_palette() -> None:
    out = direct_voice_for_revision({}, segment_index=0, iteration=1, mood="tension")
    assert out["azure_style"] in {"serious", "whispering", "sad", "terrified"}
    assert out["azure_style"] in VALID_AZURE_STYLES


def test_all_outputs_are_valid_azure_styles() -> None:
    for mood in ("", "tension", "energique", "dramatique"):
        for idx in range(6):
            for it in range(1, 4):
                out = direct_voice_for_revision({}, segment_index=idx, iteration=it, mood=mood)
                assert out["azure_style"] in VALID_AZURE_STYLES
