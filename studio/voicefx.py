"""Retouches de la voix off après synthèse.

`tighten_pauses` raccourcit les silences trop longs entre phrases (edge-tts « classique » laisse ~0,9 s
après chaque point : la vidéo paraît lente et l'attention décroche). Les silences sont détectés
par énergie, relative au niveau de la voix, et ramenés à `max_pause_s` avec un fondu court.
"""

from __future__ import annotations

import re
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


_TAG = re.compile(r"^\s*\[(?P<body>[^\]]*)\]\s*")


def parse_emphasis(text: str) -> list[tuple[str, dict[str, str]]]:
    """Lignes de narration avec réglages optionnels en tête : `[rate=+12% pitch=+4Hz] Nous !`."""
    lines: list[tuple[str, dict[str, str]]] = []
    for raw in text.splitlines():
        if not raw.strip():
            continue
        opts: dict[str, str] = {}
        m = _TAG.match(raw)
        if m:
            for part in m.group("body").replace(",", " ").split():
                key, _, value = part.partition("=")
                if key in ("rate", "pitch") and value:
                    opts[key] = value
            raw = raw[m.end():]
        lines.append((raw.strip(), opts))
    return lines


def concat_wavs(parts: list[Path], out: Path, *, gap_s: float = 0.12) -> float:
    """Concatène des WAV (même format) avec un court silence entre eux. Renvoie la durée."""
    import soundfile as sf

    chunks, sr = [], None
    for p in parts:
        data, rate = sf.read(str(p), always_2d=False)
        if sr is None:
            sr = rate
        elif rate != sr:
            raise ValueError(f"fréquences différentes : {p.name}")
        if chunks:
            chunks.append(np.zeros((int(sr * gap_s),) + data.shape[1:], dtype=data.dtype))
        chunks.append(data)
    audio = np.concatenate(chunks)
    sf.write(str(out), audio, sr, subtype="PCM_16")
    return len(audio) / sr


def combine_offset(base: str, delta: str | None) -> str:
    """Ajoute un réglage relatif de ligne au réglage global : « +30% » + « -6% » → « +24% » (idem en Hz)."""
    if not delta:
        return base
    m_base, m_delta = re.fullmatch(r"([+-]?\d+(?:\.\d+)?)(%|Hz)", base or "+0%"), re.fullmatch(
        r"([+-]?\d+(?:\.\d+)?)(%|Hz)", delta)
    if not m_delta:
        return base
    if not m_base or m_base.group(2) != m_delta.group(2):
        return delta
    total = float(m_base.group(1)) + float(m_delta.group(1))
    return f"{total:+.0f}{m_delta.group(2)}"
