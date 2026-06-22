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

_WHOOSH_GAIN_DB_BEAT_CUT = -26.0
_WHOOSH_DUR_S = 0.5
_ACCENT_DUR_S = 0.6

_SFX_MANIFEST_PATH = Path(__file__).resolve().parents[2] / "data" / "sfx" / "manifest.json"


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


def build_beat_cut_cues(
    clip_starts: list[float],
    *,
    max_per_minute: int = 12,
    video_duration_s: float | None = None,
) -> list[SfxCue]:
    """Micro-whoosh discret à chaque cut visuel intra-segment."""
    if not clip_starts:
        return []

    deduped: list[float] = []
    for t in sorted(clip_starts):
        if deduped and t - deduped[-1] < 0.3:
            continue
        deduped.append(t)

    if video_duration_s and video_duration_s > 0:
        cap = max(1, int(max_per_minute * video_duration_s / 60.0))
        deduped = deduped[:cap]

    return [
        SfxCue(time_s=max(t - 0.08, 0.0), kind="whoosh", gain_db=_WHOOSH_GAIN_DB_BEAT_CUT)
        for t in deduped
    ]


def merge_sfx_cues(*cue_lists: list[SfxCue], max_cues: int = 36) -> list[SfxCue]:
    merged: list[SfxCue] = []
    for cues in cue_lists:
        merged.extend(cues)
    merged.sort(key=lambda c: c.time_s)
    out: list[SfxCue] = []
    for cue in merged:
        if out and abs(cue.time_s - out[-1].time_s) < 0.25:
            continue
        out.append(cue)
    return out[:max_cues]


def _resolve_sfx_file(kind: str) -> Path | None:
    if not _SFX_MANIFEST_PATH.exists():
        return None
    try:
        import json

        manifest = json.loads(_SFX_MANIFEST_PATH.read_text(encoding="utf-8"))
        rel = (manifest.get(kind) or {}).get("path")
        if not rel:
            return None
        path = _SFX_MANIFEST_PATH.parent / str(rel)
        return path if path.exists() else None
    except (OSError, ValueError, TypeError):
        return None


def _synth_input(kind: str) -> tuple[str, float]:
    """Source lavfi FFmpeg ou fichier CC0 pour un SFX."""
    file_path = _resolve_sfx_file(kind)
    if file_path is not None:
        return (str(file_path), _WHOOSH_DUR_S if kind == "whoosh" else _ACCENT_DUR_S)
    if kind == "accent":
        return (f"sine=frequency=784:duration={_ACCENT_DUR_S}:sample_rate=48000", _ACCENT_DUR_S)
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
        if Path(source).exists():
            cmd += ["-t", f"{dur:.3f}", "-i", source]
        else:
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
    from agent.skills.video.ffmpeg_runtime import thread_args

    cmd += [
        "-filter_complex", ";".join(filter_parts),
        "-map", "0:v", "-map", "[aout]",
        *thread_args(),
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
    from agent.skills.video.ffmpeg_runtime import run_ffmpeg

    cmd = build_sfx_ffmpeg_command(video_path, cues, output_path)
    try:
        await run_ffmpeg(cmd, error_prefix="SFX FFmpeg error")
    except RuntimeError as exc:
        logger.warning("%s", exc)
        return None
    return output_path
