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


def _even(value: int) -> int:
    """Arrondit à un entier pair (requis par libx264 pour les dimensions)."""
    return int(value) // 2 * 2


def _build_static_filter(width: int, height: int, fps: int) -> str:
    return (
        f"scale={width}:{height}:force_original_aspect_ratio=increase:flags=lanczos,"
        f"crop={width}:{height},fps={fps}"
    )


def _focus_crop_exprs(motion_focus: list[float] | None) -> tuple[str, str]:
    if not motion_focus or len(motion_focus) < 2:
        return "(in_w-out_w)/2", "(in_h-out_h)/2"
    if len(motion_focus) >= 4:
        fcx = f"({motion_focus[0]}+{motion_focus[2]}/2)"
        fcy = f"({motion_focus[1]}+{motion_focus[3]}/2)"
    else:
        fcx, fcy = str(motion_focus[0]), str(motion_focus[1])
    x_expr = f"max(0\\,min({fcx}*in_w-out_w/2\\,in_w-out_w))"
    y_expr = f"max(0\\,min({fcy}*in_h-out_h/2\\,in_h-out_h))"
    return x_expr, y_expr


def _build_zoom_filter(
    width: int,
    height: int,
    fps: int,
    n_frames: int,
    *,
    zoom_factor: float,
    pan_enabled: bool,
    pan_direction: int,
    motion_focus: list[float] | None = None,
) -> str:
    """Filtre Ken Burns : zoom linéaire centré via crop+scale (sans zoompan).

    zoompan arrondit les coordonnées à l'entier à chaque frame, ce qui produit
    un tremblement visible. On zoome en cropant une fenêtre rétrécissante sur
    une image sur-échantillonnée, puis on scale en Lanczos vers la taille cible.
    """
    if zoom_factor <= 0:
        return _build_static_filter(width, height, fps)

    # Suréchantillonnage léger : le zoom max ne dépasse ~1+zoom_factor (≈1.03),
    # donc 1.5x suffit pour rester net. /!\ Le `scale ... eval=frame` ci-dessous
    # rééchantillonne (Lanczos) CHAQUE frame ; un facteur élevé (ex. 4x → 8K) sature
    # CPU/RAM et fait freezer la machine. Garder ce facteur bas.
    prescale_w = _even(width * 3 // 2)
    prescale_h = _even(height * 3 // 2)
    # crop n'évalue w/h qu'une fois à l'init — pas de zoom temporel possible.
    # On agrandit l'image via scale (eval=frame, variable n), puis on recadre au centre.
    z = f"(1+{zoom_factor}*n/{n_frames})"
    scale_w = f"trunc(iw*{z}/2)*2"
    scale_h = f"trunc(ih*{z}/2)*2"

    base_x, base_y = _focus_crop_exprs(motion_focus)
    if pan_enabled and pan_direction != 0:
        pan_expr = f"{pan_direction * 40}*n/{n_frames}"
        x_expr = f"{base_x}+({pan_expr})"
        y_expr = base_y
    else:
        x_expr, y_expr = base_x, base_y

    return (
        f"scale={prescale_w}:{prescale_h}:force_original_aspect_ratio=increase:flags=lanczos,"
        f"crop={prescale_w}:{prescale_h},"
        f"scale=w='{scale_w}':h='{scale_h}':eval=frame:flags=lanczos,"
        f"crop={prescale_w}:{prescale_h}:x='{x_expr}':y='{y_expr}',"
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
    from agent.skills.video.ffmpeg_runtime import filter_thread_args, run_ffmpeg, thread_args

    cmd = [
        "ffmpeg", "-y",
        *filter_thread_args(),
        "-loop", "1",
        "-i", str(image_path),
        "-vf", vf,
        "-t", str(duration_s),
        *thread_args(),
        "-c:v", "libx264", "-crf", "22", "-preset", "fast",
        "-pix_fmt", "yuv420p",
        str(output_path),
    ]
    await run_ffmpeg(cmd, error_prefix="Ken Burns FFmpeg error")


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
