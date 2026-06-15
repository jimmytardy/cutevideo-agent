from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from agent.core.config import load_agent_config

VIDEO_WIDTH = 1920
VIDEO_HEIGHT = 1080
VIDEO_FPS = 25

SHORT_WIDTH = 1080
SHORT_HEIGHT = 1920
SHORT_FPS = 30

logger = logging.getLogger(__name__)


def _load_ken_burns_config() -> dict[str, float | bool]:
    cfg = load_agent_config().get("video", {}).get("ken_burns", {})
    return {
        "enabled": bool(cfg.get("enabled", True)),
        "zoom_factor": float(cfg.get("zoom_factor", 0.03)),
        "pan_enabled": bool(cfg.get("pan_enabled", False)),
    }


def _build_static_filter(width: int, height: int, fps: int) -> str:
    return (
        f"scale={width}:{height}:force_original_aspect_ratio=increase:flags=lanczos,"
        f"crop={width}:{height},fps={fps}"
    )


def _build_zoom_filter(
    width: int,
    height: int,
    fps: int,
    n_frames: int,
    *,
    zoom_factor: float,
    pan_enabled: bool,
    pan_direction: int,
) -> str:
    """Filtre Ken Burns : zoom linéaire centré via crop+scale (sans zoompan).

    zoompan arrondit les coordonnées à l'entier à chaque frame, ce qui produit
    un tremblement visible. On zoome en cropant une fenêtre rétrécissante sur
    une image sur-échantillonnée, puis on scale en Lanczos vers la taille cible.
    """
    if zoom_factor <= 0:
        return _build_static_filter(width, height, fps)

    prescale_w = width * 4
    prescale_h = height * 4
    z = f"(1+{zoom_factor}*on/{n_frames})"
    crop_w = f"trunc({prescale_w}/{z}/2)*2"
    crop_h = f"trunc({prescale_h}/{z}/2)*2"

    if pan_enabled and pan_direction != 0:
        pan_expr = f"{pan_direction * 40}*on/{n_frames}"
        x_expr = f"trunc(({prescale_w}-({crop_w}))/2+({pan_expr})/2)*2"
    else:
        x_expr = f"trunc(({prescale_w}-({crop_w}))/2/2)*2"
    y_expr = f"trunc(({prescale_h}-({crop_h}))/2/2)*2"

    return (
        f"scale={prescale_w}:{prescale_h}:force_original_aspect_ratio=increase:flags=lanczos,"
        f"crop={prescale_w}:{prescale_h},"
        f"crop=w='{crop_w}':h='{crop_h}':x='{x_expr}':y='{y_expr}',"
        f"scale={width}:{height}:flags=lanczos,fps={fps}"
    )


async def _run_ken_burns(
    image_path: Path,
    output_path: Path,
    duration_s: float,
    width: int,
    height: int,
    fps: int,
    *,
    pan_direction: int = 0,
) -> None:
    kb_cfg = _load_ken_burns_config()
    enabled = bool(kb_cfg["enabled"])
    zoom_factor = float(kb_cfg["zoom_factor"]) if enabled else 0.0
    pan_enabled = bool(kb_cfg["pan_enabled"])
    n_frames = max(int(duration_s * fps), 1)
    if zoom_factor <= 0:
        vf = _build_static_filter(width, height, fps)
    else:
        vf = _build_zoom_filter(
            width,
            height,
            fps,
            n_frames,
            zoom_factor=zoom_factor,
            pan_enabled=pan_enabled,
            pan_direction=pan_direction,
        )
    cmd = [
        "ffmpeg", "-y",
        "-loop", "1",
        "-i", str(image_path),
        "-vf", vf,
        "-t", str(duration_s),
        "-c:v", "libx264", "-crf", "22", "-preset", "fast",
        "-pix_fmt", "yuv420p",
        str(output_path),
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(f"Ken Burns FFmpeg error: {stderr.decode()[-1000:]}")


async def apply_ken_burns_vertical(
    image_path: Path,
    output_path: Path,
    duration_s: float = 5.0,
    *,
    pan_direction: int = 0,
) -> None:
    """Ken Burns vertical 9:16."""
    await _run_ken_burns(
        image_path,
        output_path,
        duration_s,
        SHORT_WIDTH,
        SHORT_HEIGHT,
        SHORT_FPS,
        pan_direction=pan_direction,
    )


async def apply_ken_burns(
    image_path: Path,
    output_path: Path,
    duration_s: float = 5.0,
    *,
    pan_direction: int = 0,
) -> None:
    """Applique l'effet Ken Burns (zoom + pan optionnel) sur une image."""
    await _run_ken_burns(
        image_path,
        output_path,
        duration_s,
        VIDEO_WIDTH,
        VIDEO_HEIGHT,
        VIDEO_FPS,
        pan_direction=pan_direction,
    )
