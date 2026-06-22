from __future__ import annotations

import asyncio
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

_SUBCLIP_S = 2.5
_XFADE_S = 0.2


async def dynamic_recut_short(
    source_path: Path,
    output_path: Path,
    *,
    start_s: float,
    duration_s: float,
) -> float:
    """Re-découpe un extrait en sous-plans courts avec xfade (chemin crop optionnel)."""
    from agent.skills.video.ffmpeg_runtime import filter_thread_args, run_ffmpeg, thread_args

    tmp_dir = output_path.parent / f"{output_path.stem}_recut"
    tmp_dir.mkdir(parents=True, exist_ok=True)

    n_clips = max(2, min(6, int(duration_s // _SUBCLIP_S)))
    clip_dur = duration_s / n_clips
    parts: list[Path] = []

    vf = (
        f"scale={1080 * 2}:{1920 * 2}:force_original_aspect_ratio=increase,"
        f"crop={1080 * 2}:{1920 * 2},scale=1080:1920"
    )

    for i in range(n_clips):
        part = tmp_dir / f"part_{i:02d}.mp4"
        clip_start = start_s + i * clip_dur
        cmd = [
            "ffmpeg", "-y",
            *filter_thread_args(),
            "-ss", f"{clip_start:.3f}",
            "-i", str(source_path),
            "-t", f"{clip_dur:.3f}",
            "-vf", vf,
            *thread_args(),
            "-c:v", "libx264", "-crf", "22", "-preset", "fast",
            "-c:a", "aac", "-ar", "48000",
            str(part),
        ]
        await run_ffmpeg(cmd, error_prefix="dynamic recut part")
        parts.append(part)

    if len(parts) == 1:
        parts[0].replace(output_path)
        return await _probe_duration(output_path)

    inputs: list[str] = []
    for part in parts:
        inputs.extend(["-i", str(part)])

    filter_parts: list[str] = []
    v_label = "v0"
    a_label = "a0"
    filter_parts.append(f"[0:v]null[{v_label}]")
    filter_parts.append(f"[0:a]anull[{a_label}]")

    offset = clip_dur - _XFADE_S
    for j in range(1, len(parts)):
        next_v = f"v{j}"
        next_a = f"a{j}"
        out_v = f"xfv{j}"
        out_a = f"xfa{j}"
        filter_parts.append(
            f"[{v_label}][{j}:v]xfade=transition=fade:duration={_XFADE_S:.3f}:"
            f"offset={offset:.3f}[{out_v}]"
        )
        filter_parts.append(
            f"[{a_label}][{j}:a]acrossfade=d={_XFADE_S:.3f}[{out_a}]"
        )
        v_label = out_v
        a_label = out_a
        offset += clip_dur - _XFADE_S

    cmd = [
        "ffmpeg", "-y",
        *filter_thread_args(),
        *inputs,
        "-filter_complex", ";".join(filter_parts),
        "-map", f"[{v_label}]", "-map", f"[{a_label}]",
        *thread_args(),
        "-c:v", "libx264", "-crf", "20", "-preset", "medium",
        "-c:a", "aac", "-ar", "48000",
        str(output_path),
    ]
    await run_ffmpeg(cmd, error_prefix="dynamic recut concat")

    for part in parts:
        part.unlink(missing_ok=True)
    try:
        tmp_dir.rmdir()
    except OSError:
        pass

    return await _probe_duration(output_path)


async def _probe_duration(path: Path) -> float:
    proc = await asyncio.create_subprocess_exec(
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(path),
    )
    stdout, _ = await proc.communicate()
    try:
        return float(stdout.decode().strip())
    except ValueError:
        return 0.0
