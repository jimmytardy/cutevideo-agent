from __future__ import annotations

import logging
from pathlib import Path

from agent.core.montage_plan import BeatClipPlan
from agent.skills.video.filter_graph_builder import render_segment_from_clips

logger = logging.getLogger(__name__)


async def render_segment_from_plan(
    clips: list[BeatClipPlan],
    audio_path: str,
    output_path: Path,
    *,
    is_vertical: bool = False,
) -> None:
    """Assemble les clips d'un segment via filter_graph_builder (un encode)."""
    await render_segment_from_clips(
        clips,
        audio_path,
        output_path,
        is_vertical=is_vertical,
    )
