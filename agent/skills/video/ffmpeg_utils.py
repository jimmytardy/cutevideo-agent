from __future__ import annotations

import asyncio
import logging
import uuid
from pathlib import Path

import ffmpeg

from agent.core.database import AudioFile, MediaAsset

logger = logging.getLogger(__name__)

VIDEO_WIDTH = 1920
VIDEO_HEIGHT = 1080
VIDEO_FPS = 25
VIDEO_BITRATE = "8M"
AUDIO_BITRATE = "192k"
AUDIO_SAMPLE_RATE = 48000


async def assemble_long_video(
    media_assets: list[MediaAsset],
    audio_files: list[AudioFile],
    output_path: Path,
    project_id: uuid.UUID,
    min_image_duration: int = 4,
) -> float:
    """Assemble les images + audio en vidéo longue 1920x1080."""
    tmp_dir = Path(f"./tmp/{project_id}/assembly")
    tmp_dir.mkdir(parents=True, exist_ok=True)

    segments_by_order: dict[int, list[str]] = {}
    for asset in media_assets:
        if asset.local_path and Path(asset.local_path).exists():
            order = asset.segment_order or 0
            segments_by_order.setdefault(order, []).append(asset.local_path)

    audio_by_order: dict[int, AudioFile] = {
        (af.segment_order or 0): af for af in audio_files if af.local_path
    }

    video_segments: list[Path] = []
    for order in sorted(segments_by_order.keys()):
        images = segments_by_order[order]
        audio_file = audio_by_order.get(order)
        if not audio_file:
            continue

        audio_duration = audio_file.duration_s or 0
        img_duration = max(audio_duration / len(images), float(min_image_duration))

        seg_path = tmp_dir / f"segment_{order:02d}.mp4"
        await _create_segment(images, audio_file.local_path, img_duration, seg_path)
        video_segments.append(seg_path)

    if not video_segments:
        raise RuntimeError("Aucun segment vidéo à assembler")

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

    probe = ffmpeg.probe(str(output_path))
    duration = float(probe["format"]["duration"])
    logger.info("Vidéo longue assemblée : %.1f s → %s", duration, output_path)
    return duration


async def _create_segment(
    image_paths: list[str],
    audio_path: str,
    img_duration: float,
    output_path: Path,
) -> None:
    """Crée un segment vidéo avec Ken Burns sur les images et une piste audio."""
    from agent.skills.video.ken_burns import apply_ken_burns

    ken_burns_clips: list[Path] = []
    for i, img_path in enumerate(image_paths):
        clip_path = output_path.parent / f"{output_path.stem}_img{i}.mp4"
        await apply_ken_burns(Path(img_path), clip_path, duration_s=img_duration)
        ken_burns_clips.append(clip_path)

    concat_file = output_path.parent / f"{output_path.stem}_imgs.txt"
    concat_file.write_text(
        "\n".join(f"file '{p.resolve()}'" for p in ken_burns_clips),
        encoding="utf-8",
    )

    cmd = [
        "ffmpeg", "-y",
        "-f", "concat", "-safe", "0", "-i", str(concat_file),
        "-i", audio_path,
        "-c:v", "libx264", "-crf", "22", "-preset", "fast",
        "-c:a", "aac", "-b:a", AUDIO_BITRATE, "-ar", str(AUDIO_SAMPLE_RATE),
        "-shortest",
        str(output_path),
    ]
    await _run_ffmpeg(cmd)


async def _run_ffmpeg(cmd: list[str]) -> None:
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(f"FFmpeg error: {stderr.decode()[-2000:]}")
