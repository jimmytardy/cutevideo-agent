"""Rendu d'un Short 9:16 à partir d'un `timeline.json` (rôle monteur).

Toutes les encodes passent par `run_ffmpeg()` avec les garde-fous CPU
(`thread_args` en sortie, `filter_thread_args` avant le premier `-i`).
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path

from agent.skills.audio.whisper_utils import WordSegment
from agent.skills.video.ffmpeg_runtime import (
    ffmpeg_preset,
    filter_thread_args,
    run_ffmpeg,
    thread_args,
)
from studio.assets import IMAGE_EXTENSIONS, SHORT_FPS, SHORT_HEIGHT, SHORT_WIDTH
from studio.audiomix import mix_short_audio
from studio.contracts import (
    TIMELINE_DURATION_TOLERANCE_S,
    ContractError,
    Timeline,
    TimelineClip,
    load_contract,
    read_json,
    resolve_in_run_dir,
    write_json,
)
from studio.kenburns import build_static_filter, build_zoom_filter
from studio.media import probe_media
from studio.subtitles import SubtitleStyle, ass_filter, write_ass
from studio.textfx import drawtext_chain, fit_fontsize, wrap_lines

logger = logging.getLogger(__name__)

SHORT_ZOOM_FACTOR = 0.08
CLIP_TEXT_FONTSIZE = 80
CLIP_TEXT_MAX_CHARS = 18
# Haut du bloc de texte, en fraction de la hauteur (les sous-titres sont en bas).
_TEXT_TOP = {"top": 0.12, "center": 0.42, "bottom": 0.66}


def _clip_text_filter(clip: TimelineClip, work: Path, idx: int) -> str:
    lines = wrap_lines(clip.text.upper(), CLIP_TEXT_MAX_CHARS)
    fontsize = fit_fontsize(lines, SHORT_WIDTH, CLIP_TEXT_FONTSIZE)
    y_top = int(SHORT_HEIGHT * _TEXT_TOP.get(clip.text_position, _TEXT_TOP["top"]))
    return drawtext_chain(lines, work, f"text_{idx:02d}", fontsize=fontsize, y_top=str(y_top), box=True)


async def _render_clip(clip: TimelineClip, src: Path, out: Path, work: Path, idx: int) -> None:
    duration = round(clip.duration, 3)
    is_image = src.suffix.lower() in IMAGE_EXTENSIONS
    if is_image:
        n_frames = max(int(duration * SHORT_FPS), 1)
        if clip.motion == "static":
            vf = build_static_filter(SHORT_WIDTH, SHORT_HEIGHT, SHORT_FPS)
        else:
            pan = {"pan_left": -1, "pan_right": 1}.get(clip.motion, 0)
            vf = build_zoom_filter(
                SHORT_WIDTH,
                SHORT_HEIGHT,
                SHORT_FPS,
                n_frames,
                zoom_factor=SHORT_ZOOM_FACTOR,
                pan_enabled=pan != 0,
                pan_direction=pan,
            )
        inputs = ["-loop", "1", "-i", str(src)]
    else:
        vf = build_static_filter(SHORT_WIDTH, SHORT_HEIGHT, SHORT_FPS)
        # Boucle la source si elle est plus courte que le créneau.
        inputs = ["-stream_loop", "-1", "-ss", str(clip.video_offset), "-i", str(src)]

    if clip.text.strip():
        vf = f"{vf},{_clip_text_filter(clip, work, idx)}"

    cmd = [
        "ffmpeg", "-y",
        *filter_thread_args(),
        *inputs,
        "-vf", f"{vf},format=yuv420p",
        "-t", str(duration),
        "-an",
        *thread_args(),
        # Intermédiaire ré-encodé au mux final : preset rapide, qualité haute.
        "-c:v", "libx264", "-crf", "17", "-preset", "veryfast",
        "-r", str(SHORT_FPS),
        str(out),
    ]
    await run_ffmpeg(cmd, error_prefix=f"Rendu clip {idx} ({src.name})")


def _load_words(path: Path) -> list[WordSegment]:
    raw = read_json(path, [])
    return [WordSegment(word=w["word"], start=float(w["start"]), end=float(w["end"])) for w in raw]


async def _validate_inputs(run_dir: Path, timeline: Timeline) -> tuple[Path, list[Path], Path | None]:
    """Voix, médias et musique : présents, dans le run dir, voix de la durée de la timeline.

    Vérifié avant tout encodage pour échouer vite (message destiné à Claude).
    """
    voice = resolve_in_run_dir(run_dir, timeline.voice)
    if not voice.exists():
        raise ContractError(f"voix introuvable : {timeline.voice}")
    voice_duration = (await probe_media(voice))["duration_s"]
    if abs(timeline.duration - voice_duration) > TIMELINE_DURATION_TOLERANCE_S:
        raise ContractError(
            f"la timeline dure {timeline.duration:.2f}s mais la voix {voice_duration:.2f}s : "
            "le dernier clip doit finir à la fin de la voix"
        )
    sources: list[Path] = []
    for clip in timeline.clips:
        src = resolve_in_run_dir(run_dir, clip.media)
        if not src.exists():
            raise ContractError(f"média introuvable : {clip.media}")
        sources.append(src)
    music = resolve_in_run_dir(run_dir, timeline.music) if timeline.music else None
    if music is not None and not music.exists():
        raise ContractError(f"musique introuvable : {timeline.music}")
    return voice, sources, music


async def _render_video_track(timeline: Timeline, sources: list[Path], work: Path) -> Path:
    """Un segment encodé par clip, puis concaténation sans réencodage."""
    segment_paths: list[Path] = []
    for idx, (clip, src) in enumerate(zip(timeline.clips, sources)):
        seg = work / f"seg_{idx:02d}.mp4"
        await _render_clip(clip, src, seg, work, idx)
        segment_paths.append(seg)
    concat_list = work / "concat.txt"
    concat_list.write_text("".join(f"file '{p}'\n" for p in segment_paths), encoding="utf-8")
    video_only = work / "video.mp4"
    await run_ffmpeg(
        ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(concat_list),
         "-c", "copy", str(video_only)],
        error_prefix="Concat clips",
    )
    return video_only


def _subtitle_filter_args(run_dir: Path, timeline: Timeline, work: Path) -> list[str]:
    """`-vf ass=…` des sous-titres mot à mot, ou rien si désactivés / sans mots."""
    words = _load_words(resolve_in_run_dir(run_dir, timeline.words)) if timeline.subtitles else []
    if not words:
        return []
    style = SubtitleStyle(position=timeline.subtitle_position, keywords=timeline.subtitle_keywords)
    return ["-vf", ass_filter(write_ass(words, style, work / "subs.ass"))]


async def _mux(video_only: Path, audio: Path, vf_args: list[str], output_path: Path) -> None:
    # Durée explicite plutôt que `-shortest` : sa file de synchronisation garde en mémoire des
    # images brutes 1080×1920 (pic mesuré 1,76 Go contre 0,63 Go sur un Short de 31 s).
    duration = min((await probe_media(video_only))["duration_s"], (await probe_media(audio))["duration_s"])
    await run_ffmpeg(
        [
            "ffmpeg", "-y",
            *filter_thread_args(),
            "-i", str(video_only),
            "-i", str(audio),
            "-map", "0:v", "-map", "1:a",
            *vf_args,
            *thread_args(),
            "-c:v", "libx264", "-crf", "20", "-preset", ffmpeg_preset(),
            "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "192k",
            "-t", f"{duration:.3f}",
            "-movflags", "+faststart",
            str(output_path),
        ],
        error_prefix="Mux final",
    )


async def render_timeline(run_dir: Path, timeline_path: Path, output_path: Path) -> dict:
    """Rend la timeline et renvoie un résumé (durée, clips, crédits utilisés)."""
    run_dir = run_dir.resolve()
    timeline = load_contract(timeline_path, Timeline)
    voice, sources, music = await _validate_inputs(run_dir, timeline)

    output_path = resolve_in_run_dir(run_dir, str(output_path))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    # Laissé en place si le rendu échoue (diagnostic) ; recréé au rendu suivant.
    work = run_dir / ".render" / output_path.stem
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)

    video_only = await _render_video_track(timeline, sources, work)
    audio = work / "audio.m4a"
    sfx_events = [(clip.start, clip.sfx) for clip in timeline.clips if clip.sfx]
    mix = await mix_short_audio(
        voice, music, audio, music_volume=timeline.music_volume, sfx_events=sfx_events, work=work
    )
    vf_args = _subtitle_filter_args(run_dir, timeline, work)
    await _mux(video_only, audio, vf_args, output_path)
    shutil.rmtree(work, ignore_errors=True)

    info = await probe_media(output_path)
    summary = {
        "output": str(output_path.relative_to(run_dir)),
        "duration_s": info["duration_s"],
        "width": info.get("width"),
        "height": info.get("height"),
        "clips": len(timeline.clips),
        "subtitles": bool(vf_args),
        "music": timeline.music,
        "mix": mix,
        "credits": _used_credits(run_dir, timeline),
    }
    write_json(output_path.with_suffix(".render.json"), summary)
    return summary


def _used_credits(run_dir: Path, timeline: Timeline) -> list[dict]:
    """Crédits des médias effectivement utilisés (depuis media/credits.json)."""
    registry = read_json(run_dir / "media" / "credits.json", {})
    used: list[dict] = []
    seen: set[str] = set()
    paths = [c.media for c in timeline.clips] + ([timeline.music] if timeline.music else [])
    for rel in paths:
        entry = registry.get(rel)
        if entry and rel not in seen:
            seen.add(rel)
            used.append({"media": rel, **entry})
    return used
