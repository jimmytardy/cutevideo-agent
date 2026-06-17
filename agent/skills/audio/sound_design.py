from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

"""P4 — Design sonore : la *décision* manquante par-dessus le mix musical par mood.

Le bed musical par mood (energique sur le hook → calme sur la conclusion) est déjà
géré par l'éditeur. Ce module ajoute la couche d'**effets ponctuels** (SFX) :
- un « whoosh » discret sur chaque transition de segment,
- un « accent » sur les segments de révélation (hook surprenant / chiffre).

Les SFX sont **synthétisés à la volée par FFmpeg** (aucun asset requis) puis mixés
sur la piste finale, à faible volume pour ne pas masquer la narration.
"""

# Hooks qui méritent un accent sonore (révélation).
_REVEAL_HOOKS: frozenset[str] = frozenset({"fait_surprenant", "revelateur", "révélateur", "chiffre"})

# Gains (dB) : plus bas en présence de narration pour rester en arrière-plan.
_WHOOSH_GAIN_DB_VOICE = -22.0
_WHOOSH_GAIN_DB_NO_VOICE = -16.0
_ACCENT_GAIN_DB_VOICE = -20.0
_ACCENT_GAIN_DB_NO_VOICE = -14.0

_WHOOSH_DUR_S = 0.5
_ACCENT_DUR_S = 0.6


@dataclass(frozen=True)
class SfxCue:
    time_s: float
    kind: str  # "whoosh" | "accent"
    gain_db: float


def build_sfx_cues(
    segment_meta: dict[int, dict],
    *,
    max_cues: int = 24,
) -> list[SfxCue]:
    """Décide les SFX et leurs horodatages à partir du découpage en segments.

    - « whoosh » au début de chaque segment sauf le premier (transitions).
    - « accent » au début des segments de révélation (hook surprenant / chiffre).
    """
    if not segment_meta:
        return []

    ordered = sorted(segment_meta.items())
    has_narration = any(m.get("needs_voice") for m in segment_meta.values())
    whoosh_gain = _WHOOSH_GAIN_DB_VOICE if has_narration else _WHOOSH_GAIN_DB_NO_VOICE
    accent_gain = _ACCENT_GAIN_DB_VOICE if has_narration else _ACCENT_GAIN_DB_NO_VOICE

    cues: list[SfxCue] = []
    start = 0.0
    for idx, (_order, meta) in enumerate(ordered):
        if idx > 0:
            # Whoosh légèrement avant la coupe pour amorcer la transition.
            cues.append(SfxCue(time_s=max(start - 0.15, 0.0), kind="whoosh", gain_db=whoosh_gain))
        hook = str(meta.get("hook_type") or "").strip().lower()
        if hook in _REVEAL_HOOKS:
            cues.append(SfxCue(time_s=start + 0.05, kind="accent", gain_db=accent_gain))
        start += float(meta.get("duration_s", 30) or 0)

    cues.sort(key=lambda c: c.time_s)
    return cues[:max_cues]


def _synth_input(kind: str) -> tuple[str, float]:
    """Source lavfi FFmpeg pour un SFX (sans gain ni délai)."""
    if kind == "accent":
        # Ping clair (cloche douce) — sinus qui décroît rapidement.
        return (f"sine=frequency=784:duration={_ACCENT_DUR_S}:sample_rate=48000", _ACCENT_DUR_S)
    # whoosh : bruit rose filtré, balayé en fréquence par les fades.
    return (f"anoisesrc=d={_WHOOSH_DUR_S}:c=pink:r=48000:a=0.9", _WHOOSH_DUR_S)


def _shape_filter(kind: str, gain_db: float, delay_ms: int) -> str:
    """Mise en forme d'un SFX : filtrage + enveloppe + gain + délai de placement."""
    if kind == "accent":
        body = f"afade=t=out:st=0.05:d={_ACCENT_DUR_S - 0.05:.2f}"
    else:
        body = (
            f"highpass=f=200,lowpass=f=5000,"
            f"afade=t=in:st=0:d=0.1,afade=t=out:st=0.3:d={_WHOOSH_DUR_S - 0.3:.2f}"
        )
    # aformat stéréo avant amix : les sources synthétisées sont mono (évite un
    # désaccord de layout au mix, comme dans mix_multi_segment_music).
    return f"{body},aformat=channel_layouts=stereo,volume={gain_db}dB,adelay={delay_ms}|{delay_ms}"


def build_sfx_ffmpeg_command(
    video_path: Path,
    cues: list[SfxCue],
    output_path: Path,
) -> list[str]:
    """Construit la commande FFmpeg qui synthétise et mixe les SFX sur la vidéo."""
    cmd: list[str] = ["ffmpeg", "-y", "-i", str(video_path)]
    for cue in cues:
        source, dur = _synth_input(cue.kind)
        cmd += ["-f", "lavfi", "-t", f"{dur:.3f}", "-i", source]

    filter_parts: list[str] = []
    sfx_labels: list[str] = []
    for i, cue in enumerate(cues, start=1):
        label = f"sfx{i}"
        delay_ms = max(int(cue.time_s * 1000), 0)
        filter_parts.append(f"[{i}:a]{_shape_filter(cue.kind, cue.gain_db, delay_ms)}[{label}]")
        sfx_labels.append(f"[{label}]")

    mix_inputs = "[0:a]" + "".join(sfx_labels)
    filter_parts.append(
        f"{mix_inputs}amix=inputs={len(sfx_labels) + 1}:duration=first:normalize=0[aout]"
    )
    cmd += [
        "-filter_complex", ";".join(filter_parts),
        "-map", "0:v", "-map", "[aout]",
        "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
        str(output_path),
    ]
    return cmd


async def apply_sfx_cues(
    video_path: Path,
    cues: list[SfxCue],
    output_path: Path,
) -> Path | None:
    """Mixe les SFX sur la vidéo. Retourne le chemin de sortie ou None si rien à faire/échec."""
    if not cues:
        return None
    cmd = build_sfx_ffmpeg_command(video_path, cues, output_path)
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        logger.warning("SFX FFmpeg error : %s", stderr.decode()[-500:])
        return None
    return output_path
