"""Cache par ligne de `studio.tools tts` : une retouche ne resynthétise que les lignes modifiées."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

import numpy as np
import soundfile as sf

from studio import tools


def _args(**overrides) -> argparse.Namespace:
    base = dict(text_file="narration.txt", out="voice.wav", engine=None, voice=None, style=None,
                rate="+10%", pitch="+0Hz", mood="calme", max_pause=0)
    base.update(overrides)
    return argparse.Namespace(**base)


def _setup(tmp_path: Path, monkeypatch) -> list[str]:
    (tmp_path / "brief.json").write_text(json.dumps({"tts_engine": "edge-tts", "voice": "fr-FR-DeniseNeural"}),
                                         encoding="utf-8")
    calls: list[str] = []

    async def fake_generate_tts(text, output_path, *, voice, engine, **_kw):
        calls.append(text)
        sf.write(str(output_path), np.full(2400, 0.1, dtype=np.float32), 24000, subtype="PCM_16")
        return 0.1, engine

    monkeypatch.setattr("agent.skills.audio.tts.generate_tts", fake_generate_tts)
    return calls


def _tts(tmp_path: Path, text: str, **overrides) -> dict:
    (tmp_path / "narration.txt").write_text(text, encoding="utf-8")
    return asyncio.run(tools.cmd_tts(_args(**overrides), tmp_path))


def test_unchanged_lines_are_reused(tmp_path: Path, monkeypatch) -> None:
    calls = _setup(tmp_path, monkeypatch)
    first = _tts(tmp_path, "Ligne un.\nLigne deux.\n[pitch=+8Hz] Ligne trois ?")
    assert (first["lines_synthesized"], first["lines_reused"]) == (3, 0)

    calls.clear()
    second = _tts(tmp_path, "Ligne un.\nLigne deux, retouchée.\n[pitch=+8Hz] Ligne trois ?")
    assert calls == ["Ligne deux, retouchée."]
    assert (second["lines_synthesized"], second["lines_reused"]) == (1, 2)
    assert second["chars_synthesized"] == len("Ligne deux, retouchée.")
    assert sf.info(str(tmp_path / "voice.wav")).frames > 3 * 2400  # 3 lignes recollées + silences

    calls.clear()
    third = _tts(tmp_path, "Ligne un.\nLigne deux, retouchée.\n[pitch=+8Hz] Ligne trois ?")
    assert calls == [] and third["lines_reused"] == 3


def test_changed_settings_invalidate_cache(tmp_path: Path, monkeypatch) -> None:
    calls = _setup(tmp_path, monkeypatch)
    _tts(tmp_path, "Ligne un.")
    calls.clear()
    result = _tts(tmp_path, "Ligne un.", rate="+20%")
    assert calls == ["Ligne un."] and result["lines_synthesized"] == 1
