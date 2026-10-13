"""Composition de miniature (rôle miniaturiste) : fond recadré + texte incrusté."""

from __future__ import annotations

import shutil
from pathlib import Path

from agent.skills.video.ffmpeg_runtime import filter_thread_args, run_ffmpeg, thread_args
from studio.media import IMAGE_EXTENSIONS, probe_media
from studio.textfx import block_height, drawtext_chain, fit_fontsize, wrap_lines

SIZES = {"9:16": (1080, 1920), "16:9": (1280, 720)}
MAX_CHARS = {"9:16": 12, "16:9": 18}


def _parse_background(run_dir: Path, background: str) -> tuple[Path, float | None]:
    """`media/x.jpg` ou `renders/v1.mp4@3.5` (frame à 3,5 s)."""
    seek: float | None = None
    if "@" in background:
        background, at = background.rsplit("@", 1)
        seek = float(at)
    path = (run_dir / background).resolve()
    if not path.is_relative_to(run_dir.resolve()) or not path.exists():
        raise ValueError(f"fond introuvable : {background}")
    return path, seek


async def compose_thumbnail(
    run_dir: Path,
    background: str,
    text: str,
    out: Path,
    *,
    aspect: str = "9:16",
    position: str = "center",
    color: str = "yellow",
) -> dict:
    if aspect not in SIZES:
        raise ValueError(f"aspect inconnu : {aspect} (9:16 ou 16:9)")
    width, height = SIZES[aspect]
    src, seek = _parse_background(run_dir, background)
    if src.suffix.lower() not in IMAGE_EXTENSIONS:
        # Une frame demandée après la fin de la vidéo ne produit aucune image : on la borne.
        duration = (await probe_media(src))["duration_s"] or 0.0
        seek = min(1.0 if seek is None else seek, max(0.0, duration - 0.1))

    out.parent.mkdir(parents=True, exist_ok=True)
    lines = wrap_lines(text.upper(), MAX_CHARS[aspect])
    if not lines:
        raise ValueError("--text vide")
    base = int(width * (0.13 if aspect == "9:16" else 0.10))
    fontsize = fit_fontsize(lines, width, base)
    block = block_height(len(lines), fontsize)
    y_top = {
        "top": int(height * 0.08),
        "center": (height - block) // 2,
        "bottom": int(height * 0.92) - block,
    }.get(position, (height - block) // 2)
    work = out.parent / f".{out.stem}_text"
    work.mkdir(parents=True, exist_ok=True)
    text_filters = drawtext_chain(
        lines, work, "line", fontsize=fontsize, y_top=str(y_top), color=color
    )
    vf = (
        f"scale={width}:{height}:force_original_aspect_ratio=increase:flags=lanczos,"
        f"crop={width}:{height},eq=contrast=1.12:saturation=1.25,"
        # assombrit le fond pour la lisibilité du texte
        f"drawbox=x=0:y=0:w=iw:h=ih:color=black@0.18:t=fill,{text_filters}"
    )
    seek_args = ["-ss", f"{seek:.2f}"] if seek is not None else []
    await run_ffmpeg([
        "ffmpeg", "-y", *filter_thread_args(), *seek_args, "-i", str(src),
        "-vf", vf, "-frames:v", "1", *thread_args(), str(out),
    ], error_prefix="Miniature")
    shutil.rmtree(work, ignore_errors=True)
    info = await probe_media(out)
    return {"path": str(out.relative_to(run_dir.resolve())), "width": info["width"], "height": info["height"]}
