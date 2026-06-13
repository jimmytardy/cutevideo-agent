"""Tests SSML builder and voice optional logic."""

from agent.agents.narrator_agent import segment_needs_voice
from agent.skills.audio.ssml_builder import build_azure_ssml


def test_segment_needs_voice_false_when_explicit() -> None:
    assert segment_needs_voice({"needs_voice": False, "narration_text": "hello"}) is False


def test_segment_needs_voice_false_when_empty_text() -> None:
    assert segment_needs_voice({"needs_voice": True, "narration_text": ""}) is False


def test_segment_needs_voice_true_by_default_with_text() -> None:
    assert segment_needs_voice({"narration_text": "Bonjour"}) is True


def test_build_azure_ssml_contains_voice_and_style() -> None:
    ssml = build_azure_ssml(
        "Test narration",
        "fr-FR-HenriNeural",
        editorial_tone="humoristique",
        default_style="narration-professional",
    )
    assert "fr-FR-HenriNeural" in ssml
    assert "cheerful" in ssml
    assert "Test narration" in ssml
