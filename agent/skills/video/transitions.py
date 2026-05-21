from __future__ import annotations

import asyncio
from enum import Enum
from pathlib import Path


class TransitionType(str, Enum):
    FADE = "fade"
    DISSOLVE = "dissolve"
    WIPE_LEFT = "wipeleft"
    WIPE_RIGHT = "wiperight"


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

    cmd = [
        "ffmpeg", "-y",
        "-i", str(clip_a),
        "-i", str(clip_b),
        "-filter_complex",
        f"[0][1]xfade=transition={transition.value}:duration={duration_s}:offset={offset}[v];"
        f"[0:a][1:a]acrossfade=d={duration_s}[a]",
        "-map", "[v]", "-map", "[a]",
        "-c:v", "libx264", "-crf", "22",
        "-c:a", "aac",
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
