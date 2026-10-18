"""Tests prompt Gemini TTS."""

from agent.skills.audio.gemini_tts import build_gemini_tts_prompt, rate_instruction


def test_build_gemini_tts_prompt_includes_text_unchanged() -> None:
    prompt = build_gemini_tts_prompt(
        "La Révolution française commence en 1789.",
        editorial_tone="documentaire",
        mood="dramatique",
    )
    assert "La Révolution française commence en 1789." in prompt
    assert "documentaire" in prompt.lower()
    assert "dramatique" in prompt.lower()


def test_prompt_is_energetic_by_default_and_never_slow() -> None:
    prompt = build_gemini_tts_prompt("Bonjour.")
    assert "rythme soutenu" in prompt and "ton énergique et dynamique" in prompt
    assert "posé" not in prompt


def test_prompt_turns_rate_setting_into_an_instruction() -> None:
    assert rate_instruction("+0%") is None and rate_instruction("abc") is None
    assert "environ 10 % plus vite" in rate_instruction("+10%")
    assert "environ 4 % plus vite" in rate_instruction("+4%")  # continu : pas de palier qui saute entre deux lignes
    assert "environ 8 % plus lent" in rate_instruction("-8%")
    assert "environ 12 % plus vite" in build_gemini_tts_prompt("Texte", rate="+12%")


def test_explicit_mood_replaces_the_default_energy() -> None:
    prompt = build_gemini_tts_prompt("Texte", mood="mysterieux")
    assert "ton mystérieux et intrigant" in prompt and "ton énergique" not in prompt
    assert "ton solennel" in build_gemini_tts_prompt("Texte", mood="solennel")  # mood libre : jamais rendu énergique
