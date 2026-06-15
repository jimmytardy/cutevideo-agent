from __future__ import annotations

import asyncio
import logging
import uuid
from pathlib import Path

from agent.core.visual_beats import DiagramLabel, parse_visual_beats
from agent.skills.video.diagram_text_layout import analyze_diagram_text_layout, fallback_text_layout
from agent.skills.video.ffmpeg_utils import build_multi_drawtext_filter

logger = logging.getLogger(__name__)


async def _run_ffmpeg(cmd: list[str]) -> None:
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(stderr.decode()[:500] or "ffmpeg preview failed")


async def render_media_asset_label_preview(
    image_path: Path,
    output_path: Path,
    *,
    labels: list[DiagramLabel],
    narration_excerpt: str = "",
    language: str = "fr",
    visual_type: str = "",
    gemini_api_key: str | None = None,
) -> Path:
    """Applique les diagram_labels sur une image (preview dashboard)."""
    if not labels:
        raise ValueError("Aucun label à superposer")

    layout = await analyze_diagram_text_layout(
        image_path,
        labels,
        narration_excerpt=narration_excerpt,
        language=language,
        visual_type=visual_type,
        api_key=gemini_api_key,
    )
    if not layout:
        layout = fallback_text_layout(labels, visual_type=visual_type)

    vf = build_multi_drawtext_filter(layout)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if not vf:
        output_path.write_bytes(image_path.read_bytes())
        return output_path

    cmd = [
        "ffmpeg", "-y",
        "-i", str(image_path),
        "-vf", vf,
        "-frames:v", "1",
        "-q:v", "2",
        str(output_path),
    ]
    await _run_ffmpeg(cmd)
    return output_path


def find_beat_labels(
    segments: list[dict] | None,
    *,
    segment_order: int,
    beat_index: int,
) -> tuple[list[DiagramLabel], str, str]:
    """Retourne labels, narration excerpt et visual_type pour un asset."""
    for seg in segments or []:
        if int(seg.get("order", 0)) != segment_order:
            continue
        beats = parse_visual_beats(seg)
        if beat_index < len(beats):
            beat = beats[beat_index]
            labels = beat.resolved_diagram_labels()
            narration = (seg.get("narration_text") or "")[:500]
            return labels, narration, beat.visual_type
    return [], "", ""


def preview_cache_path(project_id: uuid.UUID, asset_id: uuid.UUID) -> Path:
    return Path(f"./tmp/{project_id}/previews/{asset_id}_labeled.jpg")
