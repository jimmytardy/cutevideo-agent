"""Tests chaîne de mastering audio (preset voice-studio)."""

from __future__ import annotations

from agent.skills.audio.mastering import (
    DEFAULT_MASTERING,
    build_mastering_chain,
    load_audio_mastering_config,
)


def test_build_mastering_chain_full_order() -> None:
    chain = build_mastering_chain(DEFAULT_MASTERING, deesser_available=True)
    joined = ",".join(chain)
    # Ordre studio : highpass → EQ → deesser → compresseur
    assert chain[0] == "highpass=f=80"
    assert "equalizer=f=200" in joined
    assert "equalizer=f=3000" in joined
    assert "deesser" in chain
    assert any(f.startswith("acompressor=") for f in chain)
    assert chain.index("deesser") < next(
        i for i, f in enumerate(chain) if f.startswith("acompressor=")
    )


def test_build_mastering_chain_disabled_is_empty() -> None:
    cfg = {**DEFAULT_MASTERING, "enabled": False}
    assert build_mastering_chain(cfg) == []


def test_build_mastering_chain_skips_deesser_when_unavailable() -> None:
    chain = build_mastering_chain(DEFAULT_MASTERING, deesser_available=False)
    assert "deesser" not in chain
    # Le reste de la chaîne demeure intact
    assert chain[0] == "highpass=f=80"
    assert any(f.startswith("acompressor=") for f in chain)


def test_build_mastering_chain_respects_compressor_overrides() -> None:
    cfg = {
        **DEFAULT_MASTERING,
        "compressor": {
            "threshold_db": -24,
            "ratio": 4,
            "attack_ms": 10,
            "release_ms": 200,
            "makeup_db": 3,
        },
    }
    comp = next(f for f in build_mastering_chain(cfg) if f.startswith("acompressor="))
    assert "threshold=-24dB" in comp
    assert "ratio=4" in comp
    assert "makeup=3" in comp


def test_load_audio_mastering_config_merges_defaults() -> None:
    cfg = load_audio_mastering_config()
    assert "compressor" in cfg
    assert "eq" in cfg
    assert isinstance(cfg["eq"], list)
