"""Tests résolution moteur TTS Gemini Flash."""

from agent.core.channel_config import (
    _resolve_tts_format_profiles,
    resolve_channel_config,
    tts_profile_for_channel,
)
from agent.skills.audio.tts import (
    resolve_tts_settings,
    should_use_gemini_tts,
)


class _FakeChannel:
    theme_category = "histoire"
    config = {
        "tts": {
            "short": {"engine": "gemini", "voice": "Charon"},
            "long": {"engine": "azure", "voice": "fr-FR-Vivienne:DragonHDLatestNeural"},
            "gemini": {
                "model": "gemini-2.5-flash-preview-tts",
            },
        },
    }
    brand_kit = None


def test_channel_config_resolves_tts_profiles() -> None:
    cfg = resolve_channel_config(_FakeChannel())  # type: ignore[arg-type]
    assert cfg.tts_short.engine == "gemini"
    assert cfg.tts_short.voice == "Charon"
    assert cfg.tts_long.engine == "azure"


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


def test_explicit_gemini_engine_on_long_profile(monkeypatch) -> None:
    monkeypatch.setattr(
        "agent.skills.audio.tts.settings.google_gemini_api_key",
        "test-key",
    )
    resolved = resolve_tts_settings(
        default_engine="gemini",
        default_voice="Charon",
        is_short=False,
    )
    assert resolved.engine == "gemini"
    assert resolved.voice == "Charon"


def test_tts_format_profiles_explicit_short_long() -> None:
    from agent.core.channel_config import _resolve_gemini_tts

    tts = {
        "short": {"engine": "azure", "voice": "fr-FR-DeniseNeural"},
        "long": {"engine": "gemini", "voice": "Leda"},
    }
    gemini = _resolve_gemini_tts(tts)
    short, long = _resolve_tts_format_profiles(tts, gemini)
    assert short.engine == "azure"
    assert short.voice == "fr-FR-DeniseNeural"
    assert long.engine == "gemini"
    assert long.voice == "Leda"


def test_tts_format_profiles_legacy_gemini_apply_to_long() -> None:
    from agent.core.channel_config import GeminiTtsConfig, _resolve_tts_format_profiles

    tts = {
        "engine": "azure",
        "voice": "fr-FR-Vivienne:DragonHDLatestNeural",
        "gemini": {"apply_to": "long", "voice": "Leda"},
    }
    gemini = GeminiTtsConfig(apply_to="long", voice="Leda")
    short, long = _resolve_tts_format_profiles(tts, gemini)
    assert short.engine == "azure"
    assert long.engine == "gemini"
    assert long.voice == "Leda"
