"""Tests résolution moteur TTS Gemini Flash."""

from agent.core.channel_config import _resolve_tts_format_profiles, resolve_channel_config


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
