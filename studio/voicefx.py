"""Retouches de la voix off après synthèse.

`tighten_pauses` raccourcit les silences trop longs entre phrases (edge-tts « classique » laisse ~0,9 s
après chaque point : la vidéo paraît lente et l'attention décroche). Les silences sont détectés
par énergie, relative au niveau de la voix, et ramenés à `max_pause_s` avec un fondu court.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

FRAME_S = 0.01
FADE_S = 0.012


def tighten_pauses(path: Path, *, max_pause_s: float = 0.4, threshold_db: float = -38.0) -> dict[str, float]:
    """Raccourcit en place les silences > max_pause_s. Renvoie les durées avant/après."""
    import soundfile as sf

    audio, sr = sf.read(str(path), always_2d=False)
    mono = audio if audio.ndim == 1 else audio.mean(axis=1)
    hop = int(sr * FRAME_S)
    n = len(mono) // hop
    if n == 0:
        return {"before_s": len(mono) / sr, "after_s": len(mono) / sr, "removed_s": 0.0}
    frames = mono[: n * hop].reshape(n, hop)
    rms = np.sqrt(np.mean(frames.astype(np.float64) ** 2, axis=1))
    ref = np.percentile(rms[rms > 0], 95) if np.any(rms > 0) else 1.0
    db = 20 * np.log10(np.maximum(rms, 1e-9) / ref)
    silent = db < threshold_db

    keep_frames = int(round(max_pause_s / FRAME_S))
    cuts: list[tuple[int, int]] = []  # (début, fin) en échantillons à supprimer
    i = 0
    while i < n:
        if not silent[i]:
            i += 1
            continue
        j = i
        while j < n and silent[j]:
            j += 1
        # Ni le début ni la fin du fichier (déjà gérés par la synthèse).
        if i > 0 and j < n and (j - i) > keep_frames:
            half = keep_frames // 2
            cuts.append(((i + half) * hop, (j - (keep_frames - half)) * hop))
        i = j
    if not cuts:
        dur = len(audio) / sr
        return {"before_s": round(dur, 3), "after_s": round(dur, 3), "removed_s": 0.0}

    fade = max(1, int(sr * FADE_S))
    ramp_out = np.linspace(1.0, 0.0, fade)
    ramp_in = ramp_out[::-1]
    pieces = []
    pos = 0
    for start, end in cuts:
        seg = audio[pos:start].copy()
        if len(seg) > fade:
            seg[-fade:] = (seg[-fade:].T * ramp_out).T
        pieces.append(seg)
        pos = end
        nxt = audio[pos: pos + fade]
        if len(nxt) == fade:
            audio[pos: pos + fade] = (nxt.T * ramp_in).T
    pieces.append(audio[pos:])
    out = np.concatenate(pieces)
    sf.write(str(path), out, sr, subtype="PCM_16")
    return {
        "before_s": round(len(audio) / sr, 3),
        "after_s": round(len(out) / sr, 3),
        "removed_s": round((len(audio) - len(out)) / sr, 3),
    }
