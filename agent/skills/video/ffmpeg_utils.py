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
    segment_durations: dict[int, float] | None = None,
) -> float:
    """Assemble les images + audio en vidéo longue 1920x1080."""
    tmp_dir = Path(f"./tmp/{project_id}/assembly")
    tmp_dir.mkdir(parents=True, exist_ok=True)

    image_by_order: dict[int, list[str]] = {}
    video_clip_by_order: dict[int, str] = {}
    for asset in media_assets:
        if not asset.local_path or not Path(asset.local_path).exists():
            continue
        order = asset.segment_order or 0
        if (asset.asset_type or "image") == "video":
            if order not in video_clip_by_order:
                video_clip_by_order[order] = asset.local_path
        else:
            image_by_order.setdefault(order, []).append(asset.local_path)

    audio_by_order: dict[int, AudioFile] = {
        (af.segment_order or 0): af for af in audio_files if af.local_path
    }

    all_orders = sorted(set(image_by_order) | set(video_clip_by_order))
    video_segments: list[Path] = []
    for order in all_orders:
        seg_path = tmp_dir / f"segment_{order:02d}.mp4"
        audio_file = audio_by_order.get(order)
        if order in video_clip_by_order:
            await _normalize_video_clip(
                Path(video_clip_by_order[order]), audio_file, seg_path,
                width=VIDEO_WIDTH, height=VIDEO_HEIGHT,
            )
        else:
            images = image_by_order[order]
            if audio_file:
                audio_duration = audio_file.duration_s or 0
                img_duration = max(audio_duration / len(images), float(min_image_duration))
                await _create_segment(images, audio_file.local_path, img_duration, seg_path)
            else:
                silent_duration = float((segment_durations or {}).get(order, min_image_duration * len(images)))
                img_duration = max(silent_duration / len(images), float(min_image_duration))
                await _create_silent_segment(images, img_duration, seg_path, on_screen_text="")
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

    try:
        probe = ffmpeg.probe(str(output_path))
        duration = float(probe["format"]["duration"])
    except Exception as exc:
        raise RuntimeError(f"Impossible de sonder la vidéo assemblée {output_path}: {exc}") from exc
    logger.info("Vidéo longue assemblée : %.1f s → %s", duration, output_path)
    return duration


async def assemble_vertical_short(
    media_assets: list[MediaAsset],
    audio_files: list[AudioFile],
    output_path: Path,
    project_id: uuid.UUID,
    min_image_duration: int = 3,
    segment_meta: dict[int, dict] | None = None,
) -> float:
    """Assemble un short 9:16 depuis images + audio optionnel."""
    tmp_dir = Path(f"./tmp/{project_id}/assembly_vertical")
    tmp_dir.mkdir(parents=True, exist_ok=True)

    image_by_order: dict[int, list[str]] = {}
    video_clip_by_order: dict[int, str] = {}
    for asset in media_assets:
        if not asset.local_path or not Path(asset.local_path).exists():
            continue
        order = asset.segment_order or 0
        if (asset.asset_type or "image") == "video":
            if order not in video_clip_by_order:
                video_clip_by_order[order] = asset.local_path
        else:
            image_by_order.setdefault(order, []).append(asset.local_path)

    audio_by_order: dict[int, AudioFile] = {
        (af.segment_order or 0): af for af in audio_files if af.local_path
    }

    video_segments: list[Path] = []
    meta = segment_meta or {}

    for order in sorted(set(image_by_order) | set(video_clip_by_order)):
        seg_path = tmp_dir / f"segment_{order:02d}.mp4"
        audio_file = audio_by_order.get(order)
        seg_info = meta.get(order, {})
        on_screen = str(seg_info.get("on_screen_text", ""))

        if order in video_clip_by_order:
            await _normalize_video_clip(
                Path(video_clip_by_order[order]), audio_file, seg_path,
                width=1080, height=1920,
            )
        else:
            images = image_by_order[order]
            target_d = float(seg_info.get("duration_s", min_image_duration * len(images)))
            if audio_file:
                audio_duration = audio_file.duration_s or target_d
                img_duration = max(audio_duration / len(images), float(min_image_duration))
                await _create_vertical_segment(images, audio_file.local_path, img_duration, seg_path, on_screen)
            else:
                img_duration = max(target_d / len(images), float(min_image_duration))
                await _create_vertical_silent_segment(images, img_duration, seg_path, on_screen)

        video_segments.append(seg_path)

    if not video_segments:
        raise RuntimeError("Aucun segment vertical à assembler")

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

    try:
        probe = ffmpeg.probe(str(output_path))
        return float(probe["format"]["duration"])
    except Exception as exc:
        raise RuntimeError(f"Impossible de sonder le short vertical {output_path}: {exc}") from exc


async def _create_vertical_segment(
    image_paths: list[str],
    audio_path: str,
    img_duration: float,
    output_path: Path,
    on_screen_text: str,
) -> None:
    from agent.skills.video.ken_burns import apply_ken_burns_vertical

    clips: list[Path] = []
    for i, img_path in enumerate(image_paths):
        clip_path = output_path.parent / f"{output_path.stem}_img{i}.mp4"
        await apply_ken_burns_vertical(Path(img_path), clip_path, duration_s=img_duration)
        clips.append(clip_path)

    concat_file = output_path.parent / f"{output_path.stem}_imgs.txt"
    concat_file.write_text(
        "\n".join(f"file '{p.resolve()}'" for p in clips),
        encoding="utf-8",
    )

    vf = _text_overlay_filter(on_screen_text) if on_screen_text else "null"
    cmd = [
        "ffmpeg", "-y",
        "-f", "concat", "-safe", "0", "-i", str(concat_file),
        "-i", audio_path,
        "-vf", vf,
        "-c:v", "libx264", "-crf", "22", "-preset", "fast",
        "-c:a", "aac", "-b:a", AUDIO_BITRATE, "-shortest",
        str(output_path),
    ]
    await _run_ffmpeg(cmd)


async def _create_vertical_silent_segment(
    image_paths: list[str],
    img_duration: float,
    output_path: Path,
    on_screen_text: str,
) -> None:
    from agent.skills.video.ken_burns import apply_ken_burns_vertical

    clips: list[Path] = []
    for i, img_path in enumerate(image_paths):
        clip_path = output_path.parent / f"{output_path.stem}_img{i}.mp4"
        await apply_ken_burns_vertical(Path(img_path), clip_path, duration_s=img_duration)
        clips.append(clip_path)

    concat_file = output_path.parent / f"{output_path.stem}_imgs.txt"
    concat_file.write_text(
        "\n".join(f"file '{p.resolve()}'" for p in clips),
        encoding="utf-8",
    )

    total_d = img_duration * len(image_paths)
    vf = _text_overlay_filter(on_screen_text) if on_screen_text else "null"
    cmd = [
        "ffmpeg", "-y",
        "-f", "concat", "-safe", "0", "-i", str(concat_file),
        "-f", "lavfi", "-i", f"anullsrc=r=48000:cl=mono",
        "-vf", vf,
        "-c:v", "libx264", "-crf", "22", "-preset", "fast",
        "-c:a", "aac", "-t", str(total_d),
        "-shortest",
        str(output_path),
    ]
    await _run_ffmpeg(cmd)


async def _create_silent_segment(
    image_paths: list[str],
    img_duration: float,
    output_path: Path,
    on_screen_text: str,
) -> None:
    from agent.skills.video.ken_burns import apply_ken_burns

    clips: list[Path] = []
    for i, img_path in enumerate(image_paths):
        clip_path = output_path.parent / f"{output_path.stem}_img{i}.mp4"
        await apply_ken_burns(Path(img_path), clip_path, duration_s=img_duration)
        clips.append(clip_path)

    concat_file = output_path.parent / f"{output_path.stem}_imgs.txt"
    concat_file.write_text(
        "\n".join(f"file '{p.resolve()}'" for p in clips),
        encoding="utf-8",
    )
    total_d = img_duration * len(image_paths)
    cmd = [
        "ffmpeg", "-y",
        "-f", "concat", "-safe", "0", "-i", str(concat_file),
        "-f", "lavfi", "-i", "anullsrc=r=48000:cl=mono",
        "-c:v", "libx264", "-crf", "22", "-preset", "fast",
        "-c:a", "aac", "-t", str(total_d),
        "-shortest",
        str(output_path),
    ]
    await _run_ffmpeg(cmd)


def _text_overlay_filter(text: str) -> str:
    if not text:
        return "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920"
    safe = text.replace("'", "\\'").replace(":", "\\:")[:80]
    return (
        f"scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,"
        f"drawtext=text='{safe}':fontsize=42:fontcolor=white:borderw=2:bordercolor=black:"
        f"x=(w-text_w)/2:y=h*0.75"
    )


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


async def _normalize_video_clip(
    clip_path: Path,
    audio_file: "AudioFile | None",
    output_path: Path,
    width: int = VIDEO_WIDTH,
    height: int = VIDEO_HEIGHT,
) -> None:
    """Re-encode a pre-made video clip (e.g. from Runway) to the pipeline's resolution.

    If an audio_file is provided its track replaces the clip's original audio.
    """
    vf = f"scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height}"
    if audio_file and audio_file.local_path:
        cmd = [
            "ffmpeg", "-y",
            "-i", str(clip_path),
            "-i", audio_file.local_path,
            "-vf", vf,
            "-c:v", "libx264", "-crf", "22", "-preset", "fast",
            "-c:a", "aac", "-b:a", AUDIO_BITRATE, "-ar", str(AUDIO_SAMPLE_RATE),
            "-map", "0:v:0", "-map", "1:a:0",
            "-shortest",
            str(output_path),
        ]
    else:
        cmd = [
            "ffmpeg", "-y",
            "-i", str(clip_path),
            "-f", "lavfi", "-i", "anullsrc=r=48000:cl=mono",
            "-vf", vf,
            "-c:v", "libx264", "-crf", "22", "-preset", "fast",
            "-c:a", "aac",
            "-map", "0:v:0", "-map", "1:a:0",
            "-shortest",
            str(output_path),
        ]
    await _run_ffmpeg(cmd)


async def mix_background_music(
    video_path: Path,
    music_path: Path,
    output_path: Path,
    music_volume: float = 0.08,
) -> None:
    """Mixe une piste musicale en fond sous la narration existante.

    La musique est bouclée si plus courte que la vidéo, et fondue en sortie sur 3 s.
    Le volume 0.08 (8%) garantit que la narration reste clairement audible.
    """
    try:
        probe = ffmpeg.probe(str(video_path))
        duration = float(probe["format"]["duration"])
    except Exception as exc:
        raise RuntimeError(f"Impossible de sonder {video_path} pour le mixage musique: {exc}") from exc
    fade_start = max(0.0, duration - 3.0)

    cmd = [
        "ffmpeg", "-y",
        "-i", str(video_path),
        "-stream_loop", "-1", "-i", str(music_path),
        "-filter_complex",
        (
            f"[1:a]volume={music_volume},"
            f"afade=t=out:st={fade_start:.2f}:d=3[music];"
            "[0:a][music]amix=inputs=2:duration=first[aout]"
        ),
        "-map", "0:v",
        "-map", "[aout]",
        "-c:v", "copy",
        "-c:a", "aac", "-b:a", AUDIO_BITRATE, "-ar", str(AUDIO_SAMPLE_RATE),
        "-movflags", "+faststart",
        str(output_path),
    ]
    await _run_ffmpeg(cmd)
    logger.info("Musique de fond mixée (vol=%.0f%%) → %s", music_volume * 100, output_path)


async def _run_ffmpeg(cmd: list[str]) -> None:
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(f"FFmpeg error: {stderr.decode()[-2000:]}")
