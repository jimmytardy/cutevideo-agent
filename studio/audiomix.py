"""Mixage final d'un Short : voix + musique + bruitages, normalisé pour TikTok / Shorts.

- La musique est calée **en loudness relative à la voix** (et non par un volume brut, qui donnait une
  musique inaudible ou envahissante selon le fichier) : `music_volume` 0,08 ≈ voix − 17 dB.
- Ducking doux (la musique baisse sous la voix et remonte dans les respirations), fondus d'entrée/sortie.
- Bruitages (`clip.sfx`) **synthétisés localement** (aucune question de droits) et posés sur les coupes.
- Loudness finale ≈ -14 LUFS (cible TikTok / YouTube), crêtes limitées à -1,5 dBTP.
"""

from __future__ import annotations

import math
import re
from pathlib import Path

import numpy as np

from agent.skills.video.ffmpeg_runtime import run_ffmpeg, thread_args

SR = 48000
TARGET_LUFS = -14.0
MUSIC_BELOW_VOICE_DB = 17.0
SFX_KINDS = ("whoosh", "pop", "ding", "click", "riser", "impact")
# Gain de chaque bruitage par rapport à la voix (dB) : discret, jamais au-dessus de la parole.
SFX_GAIN_DB = {"whoosh": -15, "pop": -14, "ding": -17, "click": -14, "riser": -18, "impact": -13}


# ── bruitages synthétiques ────────────────────────────────────────────────


def _bandpass_noise(n: int, centers: np.ndarray, rng: np.random.Generator, q: float = 2.0) -> np.ndarray:
    """Bruit blanc filtré par un passe-bande dont la fréquence centrale varie (biquad, échantillon par bloc)."""
    noise = rng.standard_normal(n)
    out = np.zeros(n)
    x1 = x2 = y1 = y2 = 0.0
    block = 256
    for b in range(0, n, block):
        f = float(centers[min(b, n - 1)])
        w0 = 2 * math.pi * f / SR
        alpha = math.sin(w0) / (2 * q)
        b0, b2 = alpha, -alpha
        a0, a1, a2 = 1 + alpha, -2 * math.cos(w0), 1 - alpha
        for i in range(b, min(b + block, n)):
            x0 = noise[i]
            y0 = (b0 * x0 + b2 * x2 - a1 * y1 - a2 * y2) / a0
            out[i] = y0
            x2, x1, y2, y1 = x1, x0, y1, y0
    return out


def synth_sfx(kind: str, seed: int = 7) -> np.ndarray:
    rng = np.random.default_rng(seed)
    if kind in ("whoosh", "riser"):
        dur = 0.42 if kind == "whoosh" else 1.1
        n = int(SR * dur)
        t = np.linspace(0, 1, n)
        if kind == "whoosh":
            centers = 350 * (9 ** np.sin(np.pi * t * 0.9))  # monte puis redescend
            env = np.sin(np.pi * t) ** 2
        else:
            centers = 250 * (16 ** t)
            env = t ** 2.2 * (1 - np.clip((t - 0.97) / 0.03, 0, 1))
        sig = _bandpass_noise(n, centers, rng, q=1.4) * env
    elif kind == "pop":
        n = int(SR * 0.09)
        t = np.arange(n) / SR
        freq = 900 * np.exp(-t * 30) + 260
        sig = np.sin(2 * np.pi * np.cumsum(freq) / SR) * np.exp(-t * 45)
    elif kind == "click":
        n = int(SR * 0.03)
        t = np.arange(n) / SR
        sig = (np.sin(2 * np.pi * 2400 * t) + 0.4 * rng.standard_normal(n)) * np.exp(-t * 260)
    elif kind == "ding":
        n = int(SR * 0.9)
        t = np.arange(n) / SR
        sig = sum(a * np.sin(2 * np.pi * f * t) * np.exp(-t * d)
                  for f, a, d in ((1318.5, 1.0, 5), (2637, 0.35, 8), (3951, 0.15, 11)))
        sig *= np.clip(t / 0.004, 0, 1)
    elif kind == "impact":
        n = int(SR * 0.5)
        t = np.arange(n) / SR
        thump = np.sin(2 * np.pi * (55 + 90 * np.exp(-t * 25)) * t) * np.exp(-t * 9)
        noise = _bandpass_noise(n, np.full(n, 900.0), rng, q=0.7) * np.exp(-t * 30)
        sig = thump + 0.5 * noise / (np.abs(noise).max() + 1e-9)
    else:
        raise ValueError(f"bruitage inconnu : {kind} (choix : {', '.join(SFX_KINDS)})")
    sig = sig / (np.abs(sig).max() + 1e-9)
    return sig.astype(np.float32)


def build_sfx_track(events: list[tuple[float, str]], duration: float, voice_peak_db: float, out: Path) -> Path | None:
    """Piste mono des bruitages (riser : se termine à l'instant donné ; autres : commencent)."""
    import soundfile as sf

    if not events:
        return None
    track = np.zeros(int(SR * (duration + 1.5)), dtype=np.float32)
    cache: dict[str, np.ndarray] = {}
    for t, kind in events:
        if kind not in cache:
            cache[kind] = synth_sfx(kind)
        s = cache[kind] * (10 ** ((voice_peak_db + SFX_GAIN_DB[kind]) / 20))
        start = int(SR * (t - len(s) / SR if kind == "riser" else t - (0.12 if kind == "whoosh" else 0.0)))
        start = max(0, start)
        end = min(len(track), start + len(s))
        track[start:end] += s[: end - start]
    sf.write(str(out), track[: int(SR * duration)], SR, subtype="PCM_16")
    return out


# ── mixage ────────────────────────────────────────────────────────────────


async def _measure(path: Path) -> tuple[float | None, float | None]:
    """(LUFS intégrés, crête dBFS) via ebur128."""
    import asyncio

    proc = await asyncio.create_subprocess_exec(
        "ffmpeg", "-nostats", "-i", str(path), "-map", "0:a:0", "-af", "ebur128=peak=sample",
        "-f", "null", "-", stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    _, err = await proc.communicate()
    text = err.decode(errors="replace")
    lufs = re.findall(r"I:\s+(-?[\d.]+) LUFS", text)
    peak = re.findall(r"Peak:\s+(-?[\d.]+) dBFS", text)
    return (float(lufs[-1]) if lufs else None, float(peak[-1]) if peak else None)


async def mix_short_audio(
    voice: Path,
    music: Path | None,
    out: Path,
    *,
    music_volume: float = 0.08,
    sfx_events: list[tuple[float, str]] | None = None,
    work: Path,
) -> dict[str, float | None]:
    from studio.media import probe_media

    duration = (await probe_media(voice))["duration_s"]
    voice_lufs, voice_peak = await _measure(voice)
    voice_lufs = voice_lufs if voice_lufs is not None else -16.0
    inputs = ["-i", str(voice)]
    chains = ["[0:a]aformat=sample_rates=48000:channel_layouts=mono,asplit=2[v][vkey]"]
    mix_labels = ["[v]"]
    music_gain_db = None
    if music is not None:
        music_lufs, _ = await _measure(music)
        rel_db = 20 * math.log10(max(music_volume, 1e-3) / 0.08)
        music_gain_db = (voice_lufs - MUSIC_BELOW_VOICE_DB + rel_db) - (music_lufs if music_lufs is not None else -16.0)
        fade_out = max(0.0, duration - 1.5)
        inputs += ["-stream_loop", "-1", "-i", str(music)]
        chains.append(
            f"[1:a]aformat=sample_rates=48000:channel_layouts=mono,atrim=0:{duration:.3f},"
            f"volume={music_gain_db:.2f}dB,afade=t=in:d=0.4,afade=t=out:st={fade_out:.3f}:d=1.5[m]"
        )
        # Ducking doux : ~-6 dB sous la voix, retour rapide dans les respirations.
        chains.append("[m][vkey]sidechaincompress=threshold=0.04:ratio=4:attack=30:release=350:makeup=1[md]")
        mix_labels.append("[md]")
    else:
        chains[0] = "[0:a]aformat=sample_rates=48000:channel_layouts=mono[v]"
    sfx_path = build_sfx_track(sfx_events or [], duration, voice_peak if voice_peak is not None else -3.0,
                               work / "sfx.wav")
    if sfx_path is not None:
        inputs += ["-i", str(sfx_path)]
        chains.append(f"[{2 if music is not None else 1}:a]aformat=sample_rates=48000:channel_layouts=mono[s]")
        mix_labels.append("[s]")
    chains.append(f"{''.join(mix_labels)}amix=inputs={len(mix_labels)}:duration=first:normalize=0[mix]")

    pre = work / "mix_pre.wav"
    await run_ffmpeg([
        "ffmpeg", "-y", *inputs, "-filter_complex", ";".join(chains), "-map", "[mix]",
        *thread_args(), "-c:a", "pcm_s16le", "-ar", str(SR), str(pre),
    ], error_prefix="Mixage voix/musique/bruitages")

    mix_lufs, _ = await _measure(pre)
    gain = TARGET_LUFS - mix_lufs if mix_lufs is not None else 0.0
    await run_ffmpeg([
        "ffmpeg", "-y", "-i", str(pre),
        "-af", f"volume={gain:.2f}dB,alimiter=limit=0.84:attack=3:release=60:level=disabled",
        *thread_args(), "-c:a", "aac", "-b:a", "192k", "-ar", str(SR), str(out),
    ], error_prefix="Normalisation loudness")
    pre.unlink(missing_ok=True)
    return {
        "voice_lufs": voice_lufs,
        "music_gain_db": round(music_gain_db, 1) if music_gain_db is not None else None,
        "sfx": len(sfx_events or []),
        "gain_db": round(gain, 1),
    }
