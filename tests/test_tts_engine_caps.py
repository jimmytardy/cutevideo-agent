"""Plafond TTS d'abonnement → profil voix effectivement utilisé par le brief Studio."""

from __future__ import annotations

import json
from pathlib import Path

from agent.core.channel_config import _normalize_tts_engine, _resolve_tts_format_profiles, GeminiTtsConfig
from agent.core.subscription import SubscriptionLimits, apply_subscription_caps


def test_edge_alias_is_not_mapped_to_azure() -> None:
    assert _normalize_tts_engine("edge") == "edge-tts"
    assert _normalize_tts_engine("edge-tts") == "edge-tts"
    assert _normalize_tts_engine("nimporte") == "azure"


def test_cap_applies_to_short_profile_used_by_studio() -> None:
    limits = SubscriptionLimits(tts_allowed_engines=["edge"])
    cfg = {
        "tts": {
            "engine": "azure",
            "voice": "fr-FR-Vivienne:DragonHDLatestNeural",
            "short": {"engine": "azure", "voice": "fr-FR-Vivienne:DragonHDLatestNeural"},
        }
    }
    tts = apply_subscription_caps(cfg, limits)["tts"]
    short, _long = _resolve_tts_format_profiles(tts, GeminiTtsConfig())
    assert short.engine == "edge-tts"
    # La voix Azure HD n'existe pas chez edge-tts : voix edge par défaut.
    assert ":" not in short.voice


def test_cap_keeps_allowed_edge_profile() -> None:
    limits = SubscriptionLimits(tts_allowed_engines=["edge"])
    cfg = {"tts": {"engine": "edge-tts", "short": {"engine": "edge-tts", "voice": "fr-FR-DeniseNeural"}}}
    tts = apply_subscription_caps(cfg, limits)["tts"]
    assert tts["engine"] == "edge-tts"
    assert tts["short"] == {"engine": "edge-tts", "voice": "fr-FR-DeniseNeural"}


def test_studio_tts_reads_engine_and_voice_from_brief(tmp_path: Path, monkeypatch) -> None:
    import argparse
    import asyncio

    from studio import tools

    (tmp_path / "brief.json").write_text(
        json.dumps({"tts_engine": "edge-tts", "voice": "fr-FR-DeniseNeural"}), encoding="utf-8"
    )
    (tmp_path / "narration.txt").write_text("Bonjour.", encoding="utf-8")
    calls: list[tuple[str, str]] = []

    async def fake_generate_tts(text, output_path, *, voice, engine, **_kw):
        calls.append((engine, voice))
        Path(output_path).write_bytes(b"")
        return 1.0, engine

    monkeypatch.setattr("agent.skills.audio.tts.generate_tts", fake_generate_tts)
    args = argparse.Namespace(
        text_file="narration.txt", out="voice.wav", engine=None, voice=None, style=None,
        rate=None, pitch=None, mood=None, max_pause=0,
    )
    result = asyncio.run(tools.cmd_tts(args, tmp_path))
    assert calls == [("edge", "fr-FR-DeniseNeural")]
    assert result["voice"] == "fr-FR-DeniseNeural"
