from __future__ import annotations

import asyncio
import random
from pathlib import Path

VIDEO_WIDTH = 1920
VIDEO_HEIGHT = 1080
VIDEO_FPS = 25
ZOOM_START = 1.0
ZOOM_END = 1.05


async def apply_ken_burns(
    image_path: Path,
    output_path: Path,
    duration_s: float = 5.0,
) -> None:
    """Applique un effet Ken Burns (zoom lent + léger pan) sur une image fixe."""
    n_frames = int(duration_s * VIDEO_FPS)

    direction = random.choice(["in", "out"])
    zoom_start = ZOOM_START if direction == "in" else ZOOM_END
    zoom_end = ZOOM_END if direction == "in" else ZOOM_START

    pan_x = random.choice([-1, 0, 1]) * 0.02
    pan_y = random.choice([-1, 0, 1]) * 0.02

    zoom_expr = (
        f"zoom='min(zoom+{(zoom_end - zoom_start) / n_frames:.6f},{zoom_end})'"
        f":x='iw/2-(iw/zoom/2)+{pan_x}*iw*on/{n_frames}'"
        f":y='ih/2-(ih/zoom/2)+{pan_y}*ih*on/{n_frames}'"
        f":d={n_frames}"
        f":s={VIDEO_WIDTH}x{VIDEO_HEIGHT}"
        f":fps={VIDEO_FPS}"
    )

    cmd = [
        "ffmpeg", "-y",
        "-loop", "1",
        "-i", str(image_path),
        "-vf", zoom_expr,
        "-t", str(duration_s),
        "-c:v", "libx264", "-crf", "22", "-preset", "fast",
        "-pix_fmt", "yuv420p",
        str(output_path),
    ]

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(f"Ken Burns FFmpeg error: {stderr.decode()[-1000:]}")
