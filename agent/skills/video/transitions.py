from __future__ import annotations

import asyncio
from enum import Enum
from pathlib import Path


class TransitionType(str, Enum):
    FADE = "fade"
    DISSOLVE = "dissolve"
    WIPE_LEFT = "wipeleft"
    WIPE_RIGHT = "wiperight"


async def _has_audio_stream(path: Path) -> bool:
    cmd = [
        "ffprobe", "-v", "error",
        "-select_streams", "a",
        "-show_entries", "stream=index",
        "-of", "csv=p=0",
        str(path),
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, _ = await proc.communicate()
    return bool(stdout.decode().strip())


async def add_transition(
    clip_a: Path,
    clip_b: Path,
    output_path: Path,
    transition: TransitionType = TransitionType.FADE,
    duration_s: float = 0.5,
) -> None:
    """Applique une transition entre deux clips vidéo via FFmpeg xfade."""
    probe_cmd = ["ffprobe", "-v", "error", "-show_entries", "format=duration",
                 "-of", "default=noprint_wrappers=1:nokey=1", str(clip_a)]

    proc = await asyncio.create_subprocess_exec(
        *probe_cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, _ = await proc.communicate()
    duration_a = float(stdout.decode().strip())

    offset = duration_a - duration_s

    has_audio = await _has_audio_stream(clip_a) and await _has_audio_stream(clip_b)
    xfade_filter = (
        f"[0:v][1:v]xfade=transition={transition.value}:duration={duration_s}:offset={offset}[v]"
    )
    if has_audio:
        filter_complex = f"{xfade_filter};[0:a][1:a]acrossfade=d={duration_s}[a]"
        maps = ["-map", "[v]", "-map", "[a]"]
        audio_codec = ["-c:a", "aac"]
    else:
        filter_complex = xfade_filter
        maps = ["-map", "[v]"]
        audio_codec = []

    cmd = [
        "ffmpeg", "-y",
        "-i", str(clip_a),
        "-i", str(clip_b),
        "-filter_complex", filter_complex,
        *maps,
        "-c:v", "libx264", "-crf", "22",
        *audio_codec,
        str(output_path),
    ]

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(f"Transition FFmpeg error: {stderr.decode()[-1000:]}")
