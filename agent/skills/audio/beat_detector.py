from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def detect_beats(music_path: str, *, min_interval_s: float = 0.25) -> list[float]:
    """Détecte les onsets musicaux (secondes depuis le début du fichier)."""
    path = Path(music_path)
    if not path.is_file() or path.stat().st_size == 0:
        logger.warning("Beat detection ignorée — fichier absent ou vide : %s", music_path)
        return []

    try:
        import librosa

        y, sr = librosa.load(str(path), sr=None, mono=True)
        if y.size == 0:
            return []

        onset_frames = librosa.onset.onset_detect(y=y, sr=sr, units="time")
        times = [float(t) for t in onset_frames if float(t) >= 0.0]
        return _dedupe_beats(times, min_interval_s=min_interval_s)
    except Exception as exc:
        logger.warning("Beat detection échouée pour %s : %s", music_path, exc)
        return []


def _dedupe_beats(times: list[float], *, min_interval_s: float) -> list[float]:
    if not times:
        return []
    sorted_times = sorted(times)
    deduped: list[float] = [sorted_times[0]]
    for t in sorted_times[1:]:
        if t - deduped[-1] >= min_interval_s:
            deduped.append(t)
    return deduped
