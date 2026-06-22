from __future__ import annotations

import asyncio
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

SHORT_WIDTH = 1080
SHORT_HEIGHT = 1920
SHORT_FPS = 30


async def create_short(
    source_path: Path,
    output_path: Path,
    start_s: float,
    duration_s: float,
    platform: str = "youtube",
    cta_text: str = "",
    hook_text: str = "",
    *,
    dynamic_recut: bool = False,
) -> float:
    """Crée un short 9:16 avec CTA et hook texte depuis une vidéo longue."""
    if dynamic_recut:
        from agent.skills.video.dynamic_short_recut import dynamic_recut_short

        base_duration = await dynamic_recut_short(
            source_path,
            output_path,
            start_s=start_s,
            duration_s=duration_s,
        )
        if hook_text or cta_text:
            return await _apply_hook_cta_overlay(
                output_path, platform, cta_text, hook_text, base_duration
            )
        return base_duration

    tmp_crop = output_path.parent / f"{output_path.stem}_crop.mp4"

    from agent.skills.video.ffmpeg_runtime import filter_thread_args, thread_args

    crop_cmd = [
        "ffmpeg", "-y",
        *filter_thread_args(),
        "-ss", str(start_s),
        "-i", str(source_path),
        "-t", str(duration_s),
        "-vf", (
            f"scale={SHORT_WIDTH * 2}:{SHORT_HEIGHT * 2}:force_original_aspect_ratio=increase,"
            f"crop={SHORT_WIDTH * 2}:{SHORT_HEIGHT * 2},"
            f"scale={SHORT_WIDTH}:{SHORT_HEIGHT}"
        ),
        *thread_args(),
        "-c:v", "libx264", "-crf", "22", "-preset", "fast",
        "-c:a", "aac", "-ar", "48000",
        str(tmp_crop),
    ]
    await _run(crop_cmd)

    cta_duration = 8.0
    cta_start = max(0, duration_s - cta_duration)

    cta_filter = _build_cta_filter(platform, cta_text, hook_text, cta_start, duration_s)

    overlay_cmd = [
        "ffmpeg", "-y",
        *filter_thread_args(),
        "-i", str(tmp_crop),
        "-vf", cta_filter,
        *thread_args(),
        "-c:v", "libx264", "-crf", "20", "-preset", "medium",
        "-c:a", "copy",
        str(output_path),
    ]
    await _run(overlay_cmd)

    tmp_crop.unlink(missing_ok=True)

    probe = await _probe_duration(output_path)
    return probe


async def _apply_hook_cta_overlay(
    video_path: Path,
    platform: str,
    cta_text: str,
    hook_text: str,
    duration_s: float,
) -> float:
    from agent.skills.video.ffmpeg_runtime import filter_thread_args, thread_args

    tmp_out = video_path.with_stem(video_path.stem + "_ov")
    cta_start = max(0.0, duration_s - 8.0)
    cta_filter = _build_cta_filter(platform, cta_text, hook_text, cta_start, duration_s)
    cmd = [
        "ffmpeg", "-y",
        *filter_thread_args(),
        "-i", str(video_path),
        "-vf", cta_filter,
        *thread_args(),
        "-c:v", "libx264", "-crf", "20", "-preset", "medium",
        "-c:a", "copy",
        str(tmp_out),
    ]
    await _run(cmd)
    video_path.unlink(missing_ok=True)
    tmp_out.rename(video_path)
    return await _probe_duration(video_path)


def _build_cta_filter(
    platform: str,
    cta_text: str,
    hook_text: str,
    cta_start: float,
    duration_s: float,
) -> str:
    filters: list[str] = []

    if hook_text:
        safe_hook = hook_text.replace("'", "\\'")[:80]
        filters.append(
            f"drawtext=text='{safe_hook}':"
            f"fontsize=32:fontcolor=white:box=1:boxcolor=black@0.6:boxborderw=8:"
            f"x=(w-text_w)/2:y=120:"
            f"enable='between(t,0,4)'"
        )

    if cta_text:
        cta_map = {
            "tiktok": "Vidéo complète sur YouTube ↑",
            "instagram": "Voir la vidéo complète ↑ Lien en bio",
            "youtube": "Vidéo complète → voir dans la description",
        }
        text = cta_map.get(platform, cta_text).replace("'", "\\'")
        filters.append(
            f"drawtext=text='{text}':"
            f"fontsize=28:fontcolor=white:box=1:boxcolor=black@0.7:boxborderw=8:"
            f"x=(w-text_w)/2:y=h-120:"
            f"enable='between(t,{cta_start},{duration_s})'"
        )

    return ",".join(filters) if filters else "null"


async def _run(cmd: list[str]) -> None:
    from agent.skills.video.ffmpeg_runtime import run_ffmpeg

    await run_ffmpeg(cmd)


async def _probe_duration(path: Path) -> float:
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(path),
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    stdout, _ = await proc.communicate()
    try:
        return float(stdout.decode().strip())
    except ValueError:
        return 0.0
