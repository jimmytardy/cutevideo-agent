"""Tests mixage audio adaptatif."""

from __future__ import annotations

from agent.skills.audio.audio_mixer import (
    _build_mix_filter,
    load_audio_mix_config,
    resolve_music_volume,
)


def test_resolve_music_volume_with_narration() -> None:
    cfg = {
        "music_volume_with_voice": 0.06,
        "music_volume_ambient_only": 0.04,
        "music_volume_no_voice": 0.10,
        "ducking_enabled": True,
    }
    assert resolve_music_volume(has_narration=True, has_ambient=False, cfg=cfg) == 0.06


def test_resolve_music_volume_ambient_only() -> None:
    cfg = {
        "music_volume_with_voice": 0.06,
        "music_volume_ambient_only": 0.04,
        "music_volume_no_voice": 0.10,
        "ducking_enabled": True,
    }
    assert resolve_music_volume(has_narration=False, has_ambient=True, cfg=cfg) == 0.04


def test_build_mix_filter_ducks_music_under_narration() -> None:
    filt = _build_mix_filter(music_volume=0.06, fade_start=57.0, duck_narration=True)
    assert "[music][0:a]sidechaincompress" in filt
    assert "[0:a][ducked]amix=inputs=2" in filt
    assert "[0:a][music]sidechaincompress" not in filt


def test_build_mix_filter_without_ducking_uses_amix() -> None:
    filt = _build_mix_filter(music_volume=0.08, fade_start=10.0, duck_narration=False)
    assert "sidechaincompress" not in filt
    assert "amix=inputs=2" in filt
