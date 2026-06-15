"""Tests résolution moteur TTS Gemini Flash."""

from agent.core.channel_config import resolve_channel_config
from agent.skills.audio.tts import (
    resolve_tts_settings,
    should_use_gemini_tts,
)


class _FakeChannel:
    theme_category = "histoire"
    config = {
        "tts": {
            "engine": "azure",
            "voice": "fr-FR-Vivienne:DragonHDLatestNeural",
            "gemini": {
                "apply_to": "shorts",
                "voice": "Charon",
                "model": "gemini-2.5-flash-preview-tts",
            },
        },
    }
    brand_kit = None


def test_channel_config_resolves_gemini_tts(monkeypatch) -> None:
    cfg = resolve_channel_config(_FakeChannel())  # type: ignore[arg-type]
    assert cfg.gemini_tts.apply_to == "shorts"
    assert cfg.gemini_tts.voice == "Charon"


def test_should_use_gemini_shorts_only(monkeypatch) -> None:
    monkeypatch.setattr(
        "agent.skills.audio.tts.settings.google_gemini_api_key",
        "test-key",
    )
    assert should_use_gemini_tts("shorts", is_short=True) is True
    assert should_use_gemini_tts("shorts", is_short=False) is False


def test_should_use_gemini_long_only(monkeypatch) -> None:
    monkeypatch.setattr(
        "agent.skills.audio.tts.settings.google_gemini_api_key",
        "test-key",
    )
    assert should_use_gemini_tts("long", is_short=False) is True
    assert should_use_gemini_tts("long", is_short=True) is False


def test_should_use_gemini_both(monkeypatch) -> None:
    monkeypatch.setattr(
        "agent.skills.audio.tts.settings.google_gemini_api_key",
        "test-key",
    )
    assert should_use_gemini_tts("both", is_short=True) is True
    assert should_use_gemini_tts("both", is_short=False) is True


def test_gemini_fallback_without_api_key(monkeypatch) -> None:
    monkeypatch.setattr(
        "agent.skills.audio.tts.settings.google_gemini_api_key",
        "",
    )
    monkeypatch.setattr(
        "agent.skills.audio.tts.settings.azure_speech_key",
        "",
    )
    resolved = resolve_tts_settings(
        default_engine="azure",
        default_voice="fr-FR-Vivienne:DragonHDLatestNeural",
        gemini_apply_to="shorts",
        gemini_voice="Leda",
        is_short=True,
    )
    assert resolved.engine == "edge-tts"
    assert resolved.voice == "fr-FR-Vivienne:DragonHDLatestNeural"


def test_gemini_selected_when_key_present(monkeypatch) -> None:
    monkeypatch.setattr(
        "agent.skills.audio.tts.settings.google_gemini_api_key",
        "test-key",
    )
    resolved = resolve_tts_settings(
        default_engine="azure",
        default_voice="fr-FR-Vivienne:DragonHDLatestNeural",
        gemini_apply_to="both",
        gemini_voice="Leda",
        is_short=False,
    )
    assert resolved.engine == "gemini"
    assert resolved.voice == "Leda"
