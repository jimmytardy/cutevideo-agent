"""Tests prompt Gemini TTS."""

from agent.skills.audio.gemini_tts import build_gemini_tts_prompt


def test_build_gemini_tts_prompt_includes_text_unchanged() -> None:
    prompt = build_gemini_tts_prompt(
        "La Révolution française commence en 1789.",
        editorial_tone="documentaire",
        mood="dramatique",
    )
    assert "La Révolution française commence en 1789." in prompt
    assert "documentaire" in prompt.lower()
    assert "dramatique" in prompt.lower()
