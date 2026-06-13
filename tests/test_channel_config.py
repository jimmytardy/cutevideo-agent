"""Tests channel runtime config."""

from agent.core.channel_config import resolve_channel_config


class _FakeChannel:
    theme_category = "animaux"
    config = {
        "production": {"mode": "shorts_only", "short_duration_s": 45},
        "publishing": {
            "enabled_platforms": ["youtube", "tiktok"],
            "daily_quotas": {"long": 1, "short": 5},
        },
        "editorial": {"tone": "Humoristique"},
        "tts": {"engine": "azure", "voice": "fr-FR-DeniseNeural", "style": "cheerful"},
    }
    brand_kit = None


def test_shorts_only_forces_zero_long_quota() -> None:
    cfg = resolve_channel_config(_FakeChannel())  # type: ignore[arg-type]
    assert cfg.production_mode == "shorts_only"
    assert cfg.daily_quotas.long == 0
    assert cfg.daily_quotas.short == 5
    assert cfg.enabled_platforms == ["youtube", "tiktok"]
    assert cfg.tts_voice == "fr-FR-DeniseNeural"
    assert cfg.ai_fallback.plan.value == "flux_pro"
