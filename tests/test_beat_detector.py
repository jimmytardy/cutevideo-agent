"""Tests détection de beats musicaux."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import soundfile as sf

from agent.skills.audio.beat_detector import detect_beats


def _write_click_track(path: Path, *, bpm: float = 120.0, duration_s: float = 4.0) -> None:
    sr = 22050
    interval = 60.0 / bpm
    n_samples = int(duration_s * sr)
    signal = np.zeros(n_samples, dtype=np.float32)
    click_len = int(0.01 * sr)
    t = 0.0
    while t < duration_s:
        start = int(t * sr)
        end = min(start + click_len, n_samples)
        signal[start:end] = 1.0
        t += interval
    sf.write(str(path), signal, sr)


def test_detect_beats_regular_clicks(tmp_path: Path) -> None:
    wav = tmp_path / "clicks_120bpm.wav"
    _write_click_track(wav, bpm=120.0, duration_s=4.0)

    beats = detect_beats(str(wav), min_interval_s=0.2)
    assert len(beats) >= 6

    expected_interval = 0.5
    for prev, curr in zip(beats, beats[1:]):
        assert abs((curr - prev) - expected_interval) <= 0.15


def test_detect_beats_missing_file() -> None:
    assert detect_beats("/nonexistent/track.wav") == []
