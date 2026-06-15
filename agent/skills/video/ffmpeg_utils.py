from __future__ import annotations

import logging
import uuid
from pathlib import Path
from typing import Any

import ffmpeg

from agent.core.database import AudioFile
from agent.core.montage_plan import MontagePlanData, SegmentMontagePlan
from agent.skills.video.filter_graph_builder import render_segment_from_clips

logger = logging.getLogger(__name__)

AUDIO_BITRATE = "192k"
AUDIO_SAMPLE_RATE = 48000


async def _probe_clip_duration(clip_path: Path) -> float:
    import asyncio

    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(clip_path),
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    stdout, _ = await proc.communicate()
    return float(stdout.decode().strip() or "0")


async def _run_ffmpeg(cmd: list[str]) -> None:
    import asyncio

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(f"FFmpeg error: {stderr.decode()[-2000:]}")


def _assert_audio_stream(video_path: Path) -> None:
    try:
        probe = ffmpeg.probe(str(video_path))
    except Exception as exc:
        raise RuntimeError(f"Impossible de sonder {video_path}: {exc}") from exc
    audio_streams = [s for s in probe.get("streams", []) if s.get("codec_type") == "audio"]
    if not audio_streams:
        raise RuntimeError(f"Aucune piste audio dans la vidéo assemblée : {video_path}")


async def assemble_from_montage_plan(
    montage_plan: MontagePlanData,
    audio_files: list[AudioFile],
    output_path: Path,
    project_id: uuid.UUID,
) -> float:
    """Assemble une vidéo depuis un MontagePlan (chemin unique du monteur)."""
    if not montage_plan.segments:
        raise RuntimeError("MontagePlan vide — impossible de monter la vidéo")

    tmp_dir = Path(f"./tmp/{project_id}/assembly")
    tmp_dir.mkdir(parents=True, exist_ok=True)
    audio_by_order: dict[int, AudioFile] = {
        (af.segment_order or 0): af for af in audio_files if af.local_path
    }
    is_vertical = montage_plan.is_vertical
    video_segments: list[Path] = []

    for seg_plan in sorted(montage_plan.segments, key=lambda s: s.segment_order):
        order = seg_plan.segment_order
        if not seg_plan.clips:
            raise RuntimeError(f"Segment {order} sans clips dans le MontagePlan")
        audio_file = audio_by_order.get(order)
        if not audio_file or not audio_file.local_path:
            raise RuntimeError(f"Segment {order} sans fichier audio pour le montage")
        seg_path = tmp_dir / f"segment_{order:02d}.mp4"
        await render_segment_from_clips(
            seg_plan.clips,
            audio_file.local_path,
            seg_path,
            is_vertical=is_vertical,
        )
        video_segments.append(seg_path)

    concat_list = tmp_dir / "concat.txt"
    concat_list.write_text(
        "\n".join(f"file '{seg.resolve()}'" for seg in video_segments),
        encoding="utf-8",
    )
    cmd = [
        "ffmpeg", "-y",
        "-f", "concat", "-safe", "0", "-i", str(concat_list),
        "-c:v", "libx264", "-crf", "22", "-preset", "medium",
        "-c:a", "aac", "-b:a", AUDIO_BITRATE, "-ar", str(AUDIO_SAMPLE_RATE),
        "-movflags", "+faststart",
        str(output_path),
    ]
    await _run_ffmpeg(cmd)
    _assert_audio_stream(output_path)
    probe = ffmpeg.probe(str(output_path))
    duration = float(probe["format"]["duration"])
    logger.info("Vidéo assemblée depuis plan : %.1f s → %s", duration, output_path)
    return duration


async def mix_background_music(
    video_path: Path,
    music_path: Path,
    output_path: Path,
    music_volume: float = 0.08,
    duck_narration: bool = False,
) -> None:
    try:
        probe = ffmpeg.probe(str(video_path))
        duration = float(probe["format"]["duration"])
    except Exception as exc:
        raise RuntimeError(f"Impossible de sonder {video_path} pour le mixage musique: {exc}") from exc
    fade_start = max(0.0, duration - 3.0)

    if duck_narration:
        filter_complex = (
            f"[1:a]volume={music_volume},"
            f"afade=t=out:st={fade_start:.2f}:d=3[music];"
            "[music][0:a]sidechaincompress=threshold=0.02:ratio=8:attack=200:release=1000[ducked];"
            "[0:a][ducked]amix=inputs=2:duration=first:normalize=0[aout]"
        )
    else:
        filter_complex = (
            f"[1:a]volume={music_volume},"
            f"afade=t=out:st={fade_start:.2f}:d=3[music];"
            "[0:a][music]amix=inputs=2:duration=first:normalize=0[aout]"
        )

    cmd = [
        "ffmpeg", "-y",
        "-i", str(video_path),
        "-stream_loop", "-1", "-i", str(music_path),
        "-filter_complex", filter_complex,
        "-map", "0:v",
        "-map", "[aout]",
        "-c:v", "copy",
        "-c:a", "aac", "-b:a", AUDIO_BITRATE, "-ar", str(AUDIO_SAMPLE_RATE),
        "-movflags", "+faststart",
        str(output_path),
    ]
    await _run_ffmpeg(cmd)
    logger.info(
        "Musique de fond mixée (vol=%.0f%%, duck=%s) → %s",
        music_volume * 100,
        duck_narration,
        output_path,
    )


async def assert_audio_has_signal(
    video_path: Path,
    min_mean_db: float = -50.0,
    required: bool = True,
) -> None:
    if not required:
        return
    _assert_audio_stream(video_path)
    import asyncio

    proc = await asyncio.create_subprocess_exec(
        "ffmpeg", "-i", str(video_path),
        "-af", "volumedetect",
        "-f", "null", "-",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    mean_db = -91.0
    for line in stderr.decode().splitlines():
        if "mean_volume:" in line:
            try:
                mean_db = float(line.split("mean_volume:")[1].strip().split()[0])
            except (IndexError, ValueError):
                continue
            break
    if mean_db < min_mean_db:
        raise RuntimeError(
            f"Piste audio silencieuse dans {video_path.name} "
            f"(niveau moyen {mean_db:.1f} dB) — vérifiez TTS et musique de fond"
        )


def _escape_drawtext(text: str) -> str:
    return (
        text.replace("\\", "\\\\")
        .replace("'", "\\'")
        .replace(":", "\\:")
        .replace("%", "\\%")
    )


def build_multi_drawtext_filter(
    placements: list,
    *,
    font_name: str = "DejaVu Sans",
) -> str | None:
    if not placements:
        return None
    filters: list[str] = []
    for placement in placements:
        safe = _escape_drawtext(str(placement.text))[:40]
        box = (
            ":box=1:boxcolor=black@0.6:boxborderw=6"
            if getattr(placement, "box", True)
            else ""
        )
        x_norm = float(placement.x_norm)
        y_norm = float(placement.y_norm)
        fontsize = int(getattr(placement, "fontsize", 36))
        filters.append(
            f"drawtext=font='{font_name}':text='{safe}':fontsize={fontsize}:"
            f"fontcolor=white:borderw=2:bordercolor=black@0.8"
            f"{box}:"
            f"x='(w*{x_norm})-(text_w/2)':y='(h*{y_norm})-(text_h/2)'"
        )
    return ",".join(filters)
