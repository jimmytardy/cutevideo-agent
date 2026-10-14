"""Analyse multimodale d'une vidéo rendue (outil `analyze`).

Deux voies, dans cet ordre :

1. **Gemini** (offre gratuite, `GOOGLE_GEMINI_API_KEY`) : la vidéo complète, son compris, est envoyée au modèle
   qui renvoie un avis JSON structuré selon la grille virale (`GRID`).
2. **Claude** (repli automatique, et toujours calculé) : ce que Claude peut percevoir lui-même avec Read —
   planches de frames denses (hook, chronologie, avant/après chaque coupe), transcription Whisper avec débit et
   pauses, mesures audio (loudness, rapport voix/fond, silences, hauteur et variation de la voix) et un
   spectrogramme annoté. Des alertes chiffrées (`flags`) pointent ce qui mérite d'être regardé.

Tout est écrit dans `review/<vidéo>/analysis/` ; `analysis.json` résume les mesures.
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import os
import shutil
from pathlib import Path
from typing import Any

import numpy as np

from agent.skills.video.ffmpeg_runtime import filter_thread_args, run_ffmpeg, thread_args
from studio.assets import FONT_FILE, SHEET_COLS, TILE_H, TILE_W
from studio.contracts import read_json, write_json

logger = logging.getLogger(__name__)

ANALYSIS_FPS = 5
SHEET_MAX_TILES = 16
CUT_MIN_GAP_S = 0.4
GEMINI_MODEL = os.getenv("STUDIO_GEMINI_MODEL", "gemini-2.5-flash")
GEMINI_MAX_BYTES = 19 * 1024 * 1024  # envoi en ligne (< 20 Mo)

# Grille commune à Gemini, à la critique et aux comparaisons avant/après.
GRID = {
    "hook": "0-20 : les 2 premières secondes arrêtent-elles le scroll (image forte + phrase qui ouvre une question) ?",
    "retention": "0-15 : relance toutes les 5-8 s, boucles ouvertes, rythme des plans, aucun moment d'ennui",
    "valeur": "0-15 : une seule idée claire, on apprend quelque chose de vrai et de surprenant",
    "visuels": "0-20 : chaque plan illustre ce qui est dit, finition, cohérence de style, zones sûres",
    "voix_son": "0-15 : voix naturelle et expressive (intonation, pauses, emphase), mixage voix/musique, bruitages",
    "sous_titres": "0-5 : lisibles, synchrones, mots-clés mis en valeur, hors de l'interface TikTok",
    "chute_partage": "0-10 : chute satisfaisante, fait mémorable qu'on a envie de partager, CTA court",
}


# ── utilitaires ───────────────────────────────────────────────────────────


def _rel(run_dir: Path, path: Path) -> str:
    return str(path.relative_to(run_dir))


async def _decode_frames(video: Path, work: Path) -> list[Path]:
    """Toutes les frames à ANALYSIS_FPS, en vignettes 270×480 (une seule passe ffmpeg)."""
    work.mkdir(parents=True, exist_ok=True)
    await run_ffmpeg([
        "ffmpeg", "-y", *filter_thread_args(), "-i", str(video),
        "-vf", f"fps={ANALYSIS_FPS},scale={TILE_W}:{TILE_H}:force_original_aspect_ratio=increase,"
               f"crop={TILE_W}:{TILE_H}",
        *thread_args(), "-q:v", "4", str(work / "f_%05d.jpg"),
    ], error_prefix="Analyse : décodage des frames")
    return sorted(work.glob("f_*.jpg"))


def _frame_time(index: int) -> float:
    # fps=N échantillonne au centre de chaque intervalle de 1/N s.
    return (index + 0.5) / ANALYSIS_FPS


def _detect_cuts(frames: list[Path]) -> tuple[list[float], list[float]]:
    """Coupes (s) et énergie de mouvement par frame, à partir des vignettes."""
    from PIL import Image

    grays = [
        np.asarray(Image.open(f).convert("L").resize((68, 120)), dtype=np.float32) for f in frames
    ]
    diffs = [0.0] + [float(np.mean(np.abs(b - a))) for a, b in zip(grays, grays[1:])]
    cuts: list[float] = []
    for i in range(1, len(diffs)):
        local = sorted(diffs[max(1, i - 5): i] + diffs[i + 1: i + 6]) or [0.0]
        baseline = local[len(local) // 2]
        if diffs[i] > 22 and diffs[i] > 3 * baseline + 6:
            t = round((_frame_time(i - 1) + _frame_time(i)) / 2, 2)
            if not cuts or t - cuts[-1] >= CUT_MIN_GAP_S:
                cuts.append(t)
    return cuts, diffs


def _label_tile(src: Path, label: str, *, highlight: bool = False):
    from PIL import Image, ImageDraw, ImageFont

    img = Image.open(src).convert("RGB")
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype(FONT_FILE, 24)
    except OSError:
        font = ImageFont.load_default()
    box = draw.textbbox((8, 8), label, font=font)
    draw.rectangle((box[0] - 5, box[1] - 5, box[2] + 5, box[3] + 5), fill=(200, 0, 0) if highlight else (0, 0, 0))
    draw.text((8, 8), label, font=font, fill=(255, 230, 0))
    # Repères des zones sûres TikTok : bas (légende/boutons) et colonne droite (icônes).
    h, w = img.height, img.width
    draw.line((0, int(h * 0.80), w, int(h * 0.80)), fill=(0, 200, 255), width=1)
    draw.line((int(w * 0.86), int(h * 0.35), int(w * 0.86), int(h * 0.80)), fill=(0, 200, 255), width=1)
    return img


def _build_sheets(tiles: list[tuple[Path, str, bool]], out_prefix: Path) -> list[Path]:
    from PIL import Image

    sheets: list[Path] = []
    for n, start in enumerate(range(0, len(tiles), SHEET_MAX_TILES), start=1):
        chunk = tiles[start: start + SHEET_MAX_TILES]
        cols = min(SHEET_COLS, len(chunk))
        rows = math.ceil(len(chunk) / cols)
        sheet = Image.new("RGB", (cols * (TILE_W + 4) + 4, rows * (TILE_H + 4) + 4), "white")
        for i, (path, label, hl) in enumerate(chunk):
            sheet.paste(_label_tile(path, label, highlight=hl), (4 + (i % cols) * (TILE_W + 4), 4 + (i // cols) * (TILE_H + 4)))
        out = out_prefix.with_name(f"{out_prefix.name}_{n}.png")
        sheet.save(out, optimize=True)
        sheets.append(out)
    return sheets


def _nearest(frames: list[Path], t: float) -> Path:
    return frames[min(len(frames) - 1, max(0, round(t * ANALYSIS_FPS - 0.5)))]


# ── audio ─────────────────────────────────────────────────────────────────


async def _extract_wav(video: Path, wav: Path) -> None:
    await run_ffmpeg([
        "ffmpeg", "-y", "-i", str(video), "-vn", *thread_args(),
        "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(wav),
    ], error_prefix="Analyse : extraction audio")


def _speech_metrics(words: list[dict[str, Any]], duration: float) -> dict[str, Any]:
    if not words:
        return {"words": 0}
    pauses = []
    for a, b in zip(words, words[1:]):
        gap = b["start"] - a["end"]
        if gap >= 0.35:
            pauses.append({"at": round(a["end"], 2), "s": round(gap, 2), "after": a["word"]})
    windows = []
    for w0 in range(0, int(math.ceil(duration)), 5):
        n = sum(1 for w in words if w0 <= w["start"] < w0 + 5)
        windows.append({"t": w0, "wps": round(n / 5, 2)})
    speaking = words[-1]["end"] - words[0]["start"]
    return {
        "words": len(words),
        "first_word_s": round(words[0]["start"], 2),
        "last_word_s": round(words[-1]["end"], 2),
        "words_per_s": round(len(words) / max(speaking, 0.1), 2),
        "words_per_min": round(60 * len(words) / max(speaking, 0.1)),
        "pauses": pauses,
        "longest_pause_s": max((p["s"] for p in pauses), default=0.0),
        "rate_by_5s": windows,
    }


def _audio_metrics(wav: Path, words: list[dict[str, Any]], duration: float) -> tuple[dict[str, Any], dict[str, Any]]:
    """Mesures audio + séries pour le spectrogramme."""
    import librosa

    y, sr = librosa.load(str(wav), sr=16000, mono=True)
    hop = 320  # 20 ms
    rms = librosa.feature.rms(y=y, frame_length=1024, hop_length=hop)[0]
    db = 20 * np.log10(np.maximum(rms, 1e-6))
    times = librosa.frames_to_time(np.arange(len(db)), sr=sr, hop_length=hop)

    speech_mask = np.zeros(len(db), dtype=bool)
    for w in words:
        speech_mask[(times >= w["start"]) & (times <= w["end"])] = True
    gap_mask = ~speech_mask
    if words:
        gap_mask &= (times > words[0]["start"]) & (times < words[-1]["end"])

    speech_db = float(np.median(db[speech_mask])) if speech_mask.any() else None
    bed_db = float(np.median(db[gap_mask])) if gap_mask.sum() > 10 else None

    # Silences francs (> 0,4 s sous -45 dBFS)
    silent = db < -45
    silences, start = [], None
    for i, s in enumerate(np.append(silent, False)):
        if s and start is None:
            start = i
        elif not s and start is not None:
            if (i - start) * hop / sr >= 0.4:
                silences.append({"at": round(float(times[start]), 2), "s": round((i - start) * hop / sr, 2)})
            start = None

    # Hauteur de la voix (pyin) et variation en demi-tons.
    f0, voiced, _ = librosa.pyin(y, fmin=65, fmax=420, sr=sr, frame_length=1280, hop_length=hop)
    f0_times = librosa.frames_to_time(np.arange(len(f0)), sr=sr, hop_length=hop)
    valid = voiced & ~np.isnan(f0)
    pitch: dict[str, Any] = {}
    if valid.sum() > 20:
        hz = f0[valid]
        st = 12 * np.log2(hz / np.median(hz))
        pitch = {
            "median_hz": round(float(np.median(hz)), 1),
            "std_semitones": round(float(np.std(st)), 2),
            "range_p10_p90_semitones": round(float(np.percentile(st, 90) - np.percentile(st, 10)), 2),
        }
        # Variation par phrase (mots regroupés jusqu'à une pause ≥ 0,35 s)
        phrases, cur = [], []
        for w in words:
            if cur and w["start"] - cur[-1]["end"] >= 0.35:
                phrases.append(cur)
                cur = []
            cur.append(w)
        if cur:
            phrases.append(cur)
        per_phrase = []
        for ph in phrases:
            m = valid & (f0_times >= ph[0]["start"]) & (f0_times <= ph[-1]["end"])
            if m.sum() > 10:
                s = 12 * np.log2(f0[m] / np.median(hz))
                per_phrase.append({
                    "start": round(ph[0]["start"], 2),
                    "text": " ".join(w["word"] for w in ph)[:60],
                    "std_semitones": round(float(np.std(s)), 2),
                    "end_drop_semitones": round(float(np.mean(s[-max(3, len(s) // 5):]) - np.mean(s)), 2),
                })
        pitch["phrases"] = per_phrase

    segments = []
    for t0 in np.arange(0, duration, 2.0):
        m = (times >= t0) & (times < t0 + 2.0)
        if m.any():
            segments.append({"t": round(float(t0), 1), "rms_db": round(float(np.mean(db[m])), 1)})

    metrics = {
        "speech_rms_db": round(speech_db, 1) if speech_db is not None else None,
        "bed_rms_db": round(bed_db, 1) if bed_db is not None else None,
        # Écart voix / fond (musique + bruitages entendus dans les pauses de la voix).
        "speech_to_bed_db": round(speech_db - bed_db, 1) if speech_db is not None and bed_db is not None else None,
        "silences": silences,
        "pitch": pitch,
        "rms_by_2s": segments,
    }
    series = {"y": y, "sr": sr, "f0": f0, "f0_times": f0_times, "db": db, "times": times}
    return metrics, series


def _refine_pauses(speech: dict[str, Any], series: dict[str, Any], speech_db: float | None) -> None:
    """Durée acoustique réelle de chaque pause : Whisper coupe les fins de mots tôt et gonfle les écarts.

    Une trame compte comme silence si elle est 20 dB sous le niveau médian de la parole (la musique de fond
    reste donc « silence de voix »)."""
    if not speech.get("pauses") or speech_db is None:
        return
    db, times = series["db"], series["times"]
    frame = float(times[1] - times[0]) if len(times) > 1 else 0.02
    for p in speech["pauses"]:
        m = (times >= p["at"]) & (times <= p["at"] + p["s"])
        p["whisper_s"] = p["s"]
        p["s"] = round(float(np.sum(db[m] < speech_db - 20)) * frame, 2)
    speech["pauses"] = [p for p in speech["pauses"] if p["s"] >= 0.3]
    speech["longest_pause_s"] = max((p["s"] for p in speech["pauses"]), default=0.0)


def _plot_audio(series: dict[str, Any], words: list[dict[str, Any]], cuts: list[float], out: Path) -> None:
    """Spectrogramme + courbe de hauteur + niveau, une bande par tranche de 20 s."""
    import librosa
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    y, sr = series["y"], series["sr"]
    duration = len(y) / sr
    chunk = 20.0
    n = max(1, math.ceil(duration / chunk))
    mel = librosa.feature.melspectrogram(y=y, sr=sr, n_fft=1024, hop_length=320, n_mels=80, fmax=8000)
    mel_db = librosa.power_to_db(mel, ref=np.max)
    fig, axes = plt.subplots(n * 2, 1, figsize=(16, 3.2 * n), squeeze=False,
                             gridspec_kw={"height_ratios": [3, 1] * n})
    for k in range(n):
        t0, t1 = k * chunk, min(duration, (k + 1) * chunk)
        ax, axl = axes[2 * k][0], axes[2 * k + 1][0]
        f0 = int(t0 * sr / 320)
        f1 = int(t1 * sr / 320)
        ax.imshow(mel_db[:, f0:f1], origin="lower", aspect="auto", extent=(t0, t1, 0, 80), cmap="magma")
        mask = (series["f0_times"] >= t0) & (series["f0_times"] < t1)
        f0hz = series["f0"][mask]
        # Hauteur reportée sur l'échelle 0-80 (65-420 Hz en log)
        scaled = 80 * (np.log2(np.clip(f0hz, 65, 420)) - np.log2(65)) / (np.log2(420) - np.log2(65))
        ax.plot(series["f0_times"][mask], scaled, color="cyan", linewidth=1.2)
        for c in cuts:
            if t0 <= c < t1:
                ax.axvline(c, color="lime", linewidth=1, linestyle="--")
        for w in words:
            if t0 <= w["start"] < t1:
                ax.text(w["start"], 74, w["word"], color="white", fontsize=7, rotation=50, va="top")
        ax.set_xlim(t0, t0 + chunk)
        ax.set_yticks([])
        ax.set_ylabel("mel + F0", fontsize=8)
        m = (series["times"] >= t0) & (series["times"] < t1)
        axl.plot(series["times"][m], series["db"][m], color="black", linewidth=0.8)
        axl.axhline(-45, color="red", linewidth=0.6)
        axl.set_xlim(t0, t0 + chunk)
        axl.set_ylim(-70, 0)
        axl.set_ylabel("dBFS", fontsize=8)
        axl.tick_params(labelsize=7)
    fig.suptitle("Spectrogramme (mel), hauteur de voix (cyan), coupes (vert), niveau RMS (bas)", fontsize=10)
    fig.tight_layout()
    fig.savefig(out, dpi=72)
    plt.close(fig)


# ── alertes ───────────────────────────────────────────────────────────────


def _flags(m: dict[str, Any]) -> list[str]:
    flags: list[str] = []
    v = m["visual"]
    if v["first_cut_s"] is None or v["first_cut_s"] > 2.5:
        flags.append(f"hook : première coupe à {v['first_cut_s']} s (> 2,5 s) — l'image d'ouverture doit bouger vite")
    if v["longest_shot_s"] > 5:
        flags.append(f"rythme : plan le plus long {v['longest_shot_s']} s à {v['longest_shot_at']} s (> 5 s)")
    for st in v["static_spans"]:
        flags.append(f"image quasi figée {st['s']} s à partir de {st['at']} s")
    s = m.get("speech", {})
    if s.get("words"):
        if s["first_word_s"] > 0.6:
            flags.append(f"voix : premier mot à {s['first_word_s']} s (le hook doit partir tout de suite)")
        if s["words_per_s"] < 2.4:
            flags.append(f"voix : débit lent {s['words_per_s']} mots/s (viral ≈ 2,8-3,4)")
        if s["words_per_s"] > 3.8:
            flags.append(f"voix : débit très rapide {s['words_per_s']} mots/s")
        if s["longest_pause_s"] > 1.0:
            flags.append(f"voix : pause de {s['longest_pause_s']} s")
    a = m.get("audio", {})
    lufs = m.get("loudness_lufs")
    if lufs is not None and not -16.5 <= lufs <= -12:
        flags.append(f"son : loudness {lufs} LUFS hors de [-16,5 ; -12] (TikTok ≈ -14)")
    ratio = a.get("speech_to_bed_db")
    if ratio is not None and ratio < 10:
        flags.append(f"son : voix seulement {ratio} dB au-dessus du fond (musique trop forte ?)")
    pitch = a.get("pitch") or {}
    if pitch.get("std_semitones") is not None and pitch["std_semitones"] < 2.0:
        flags.append(f"voix : intonation plate (écart-type {pitch['std_semitones']} demi-tons, expressif ≥ 2,5)")
    for sil in a.get("silences", []):
        if sil["at"] > 0.3 and sil["at"] < m["duration_s"] - 1:
            flags.append(f"son : silence de {sil['s']} s à {sil['at']} s")
    return flags


# ── Gemini ────────────────────────────────────────────────────────────────


def _gemini_prompt(context: str) -> str:
    grid = "\n".join(f'- "{k}" : {v}' for k, v in GRID.items())
    return (
        "Tu es un expert des Shorts TikTok/YouTube explicatifs francophones viraux. Regarde ET écoute toute la "
        "vidéo, puis réponds UNIQUEMENT par un objet JSON :\n"
        '{"scores": {<critère>: note}, "total": note/100, "hook": "…", "rythme": "…", '
        '"coherence_image_voix": "…", "voix": "naturel, intonation, débit, défauts précis horodatés", '
        '"musique_mixage": "…", "sous_titres": "…", "moments_ennui": [{"t": s, "pourquoi": "…"}], '
        '"potentiel_viral": "…", "corrections": ["action précise horodatée", …]}\n'
        f"Critères :\n{grid}\n{context}"
    )


async def _gemini_review(video: Path, context: str) -> dict[str, Any]:
    from agent.core.config import settings

    key = settings.google_gemini_api_key or os.getenv("GEMINI_API_KEY")
    if not key:
        raise RuntimeError("GOOGLE_GEMINI_API_KEY absente")
    if video.stat().st_size > GEMINI_MAX_BYTES:
        raise RuntimeError("vidéo trop lourde pour un envoi en ligne")
    from google import genai
    from google.genai import types

    def _call() -> str:
        client = genai.Client(api_key=key)
        resp = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=[types.Content(role="user", parts=[
                types.Part.from_bytes(data=video.read_bytes(), mime_type="video/mp4"),
                types.Part.from_text(text=_gemini_prompt(context)),
            ])],
            config=types.GenerateContentConfig(response_mime_type="application/json", temperature=0.2),
        )
        return resp.text or ""

    text = await asyncio.wait_for(asyncio.to_thread(_call), timeout=180)
    return json.loads(text)


# ── point d'entrée ────────────────────────────────────────────────────────


async def _gemini_section(engine: str, video: Path, context: str) -> dict[str, Any]:
    """Revue Gemini si possible ; `source` indique qui a produit le diagnostic."""
    review, error = None, None
    if engine in ("auto", "gemini"):
        try:
            review = await _gemini_review(video, context)
        except Exception as exc:  # repli Claude
            error = f"{type(exc).__name__}: {str(exc)[:200]}"
            logger.warning("Analyse Gemini indisponible : %s", error)
            if engine == "gemini":
                raise
    section: dict[str, Any] = {"gemini": review} if review is not None else {}
    section["source"] = "gemini" if review is not None else "claude"
    if error:
        section["gemini_error"] = error
    return section


def _timeline_cuts(timeline_file: Path | None, duration: float) -> list[float] | None:
    """Coupes connues par la timeline (les coupes entre animations au même fond échappent à la détection)."""
    if not timeline_file or not timeline_file.exists():
        return None
    try:
        clips = read_json(timeline_file)["clips"]
        if abs(float(clips[-1]["end"]) - duration) <= 0.6:
            return [round(float(c["start"]), 2) for c in clips[1:]]
    except (KeyError, ValueError, TypeError, IndexError):
        pass
    return None


def _static_spans(diffs: list[float]) -> list[dict[str, float]]:
    """Plans « figés » : ≥ 3 s sans coupe et presque sans mouvement."""
    spans, run_start = [], None
    for i, d in enumerate(diffs + [99.0]):
        if d < 0.6 and i > 0:
            run_start = i if run_start is None else run_start
        else:
            if run_start is not None and (i - run_start) / ANALYSIS_FPS >= 3.0:
                spans.append({"at": round(_frame_time(run_start), 1), "s": round((i - run_start) / ANALYSIS_FPS, 1)})
            run_start = None
    return spans


def _visual_metrics(cuts: list[float], cuts_source: str, diffs: list[float], duration: float) -> dict[str, Any]:
    bounds = [0.0, *cuts, duration]
    shots = [round(b - a, 2) for a, b in zip(bounds, bounds[1:])]
    longest = int(np.argmax(shots)) if shots else 0
    return {
        "cuts_source": cuts_source,
        "cuts": cuts,
        "shots": len(shots),
        "mean_shot_s": round(float(np.mean(shots)), 2) if shots else duration,
        "longest_shot_s": shots[longest] if shots else duration,
        "longest_shot_at": bounds[longest],
        "first_cut_s": cuts[0] if cuts else None,
        "cuts_per_10s": round(10 * len(cuts) / max(duration, 0.1), 2),
        "motion_by_s": [round(float(np.mean(diffs[i: i + ANALYSIS_FPS])), 1) for i in range(0, len(diffs), ANALYSIS_FPS)],
        "static_spans": _static_spans(diffs),
    }


def _review_sheets(
    run_dir: Path, frames: list[Path], cuts: list[float], duration: float, every_s: float, out_dir: Path
) -> dict[str, list[str]]:
    """Planches à lire : accroche (3 premières s), frise complète, avant/après chaque coupe."""
    hook_tiles = [(_nearest(frames, t), f"{t:.2f}s", False) for t in np.arange(0.0, min(3.0, duration), 0.25)]
    cut_set = set(round(c * ANALYSIS_FPS) for c in cuts)
    timeline_tiles = [
        (_nearest(frames, t), f"{t:.1f}s", round(t * ANALYSIS_FPS) in cut_set)
        for t in np.arange(every_s / 2, duration, every_s)
    ]
    cut_tiles = []
    for c in cuts:
        cut_tiles.append((_nearest(frames, c - 0.25), f"{c:.1f}s avant", False))
        cut_tiles.append((_nearest(frames, c + 0.25), f"{c:.1f}s après", True))
    return {
        "hook": [_rel(run_dir, p) for p in _build_sheets(hook_tiles, out_dir / "hook")],
        "timeline": [_rel(run_dir, p) for p in _build_sheets(timeline_tiles, out_dir / "timeline")],
        "cuts": [_rel(run_dir, p) for p in _build_sheets(cut_tiles, out_dir / "cuts")] if cut_tiles else [],
    }


async def _video_words(wav: Path, words_file: Path | None) -> list[dict[str, Any]]:
    """Mots horodatés : `words.json` du run s'il existe, sinon transcription Whisper."""
    if words_file and words_file.exists():
        return read_json(words_file)
    from agent.skills.audio.whisper_utils import transcribe_to_words

    model = os.getenv("STUDIO_WHISPER_MODEL", "small")
    segs = await transcribe_to_words([wav], model_name=model, language="fr")
    return [{"word": w.word, "start": round(w.start, 3), "end": round(w.end, 3)} for w in segs]


async def _audio_section(
    video: Path, work: Path, out_dir: Path, words_file: Path | None, duration: float, cuts: list[float]
) -> tuple[dict[str, Any], Path]:
    """Transcription, débit, pauses, niveaux et spectrogramme annoté (audio.png)."""
    wav = work / "audio.wav"
    await _extract_wav(video, wav)
    words = await _video_words(wav, words_file)
    section: dict[str, Any] = {
        "transcript": " ".join(w["word"] for w in words),
        "speech": _speech_metrics(words, duration),
    }
    audio_metrics, series = await asyncio.to_thread(_audio_metrics, wav, words, duration)
    section["audio"] = audio_metrics
    _refine_pauses(section["speech"], series, audio_metrics.get("speech_rms_db"))
    audio_png = out_dir / "audio.png"
    await asyncio.to_thread(_plot_audio, series, words, cuts, audio_png)
    write_json(out_dir / "words.json", words, indent=1)
    return section, audio_png


def _compact_summary(run_dir: Path, result: dict[str, Any], path: Path) -> dict[str, Any]:
    """Sortie compacte pour Claude : les séries longues restent dans analysis.json."""
    summary = {k: v for k, v in result.items() if k not in ("grid", "transcript")}
    summary["visual"] = {k: v for k, v in result["visual"].items() if k != "motion_by_s"}
    if "speech" in summary:
        summary["speech"] = {k: v for k, v in result["speech"].items() if k != "rate_by_5s"}
    if "audio" in summary:
        summary["audio"] = {k: v for k, v in result["audio"].items() if k != "rms_by_2s"}
    summary["analysis"] = _rel(run_dir, path)
    return summary


async def analyze_video(
    run_dir: Path,
    video: Path,
    out_dir: Path,
    *,
    engine: str = "auto",
    words_file: Path | None = None,
    timeline_file: Path | None = None,
    every_s: float = 1.0,
    context: str = "",
) -> dict[str, Any]:
    from studio.media import loudness, probe_media

    info = await probe_media(video)
    duration = float(info["duration_s"])
    out_dir.mkdir(parents=True, exist_ok=True)
    work = out_dir / ".work"
    shutil.rmtree(work, ignore_errors=True)

    result: dict[str, Any] = {"video": _rel(run_dir, video), "duration_s": round(duration, 2), "grid": GRID}
    result.update(await _gemini_section(engine, video, context))

    # ── images ──
    frames = await _decode_frames(video, work / "frames")
    cuts, diffs = _detect_cuts(frames)
    timeline_cuts = _timeline_cuts(timeline_file, duration)
    if timeline_cuts is not None:
        cuts = timeline_cuts
    result["visual"] = _visual_metrics(cuts, "timeline" if timeline_cuts is not None else "image", diffs, duration)
    sheets = _review_sheets(run_dir, frames, cuts, duration, every_s, out_dir)

    # ── son ──
    result["loudness_lufs"] = await loudness(video) if info["has_audio"] else None
    audio_png = None
    if info["has_audio"]:
        audio, audio_png = await _audio_section(video, work, out_dir, words_file, duration, cuts)
        result.update(audio)
    result["flags"] = _flags(result)
    result["read"] = {**sheets, "audio": _rel(run_dir, audio_png) if audio_png else None}
    shutil.rmtree(work, ignore_errors=True)

    path = out_dir / "analysis.json"
    write_json(path, result, indent=1)
    return _compact_summary(run_dir, result, path)
