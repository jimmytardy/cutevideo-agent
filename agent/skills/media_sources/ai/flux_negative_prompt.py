from __future__ import annotations

from agent.skills.media_sources.ai.prompt_builder import DIAGRAM_VISUAL_TYPES

FLUX_DIAGRAM_NEGATIVE_PROMPT = (
    "text, letters, words, typography, caption, title, watermark, logo, "
    "label boxes, empty frames, text placeholders, infographic placeholders, "
    "banner, readable characters, numbers"
)


def flux_negative_prompt_for_visual_type(visual_type: str) -> str | None:
    if visual_type in DIAGRAM_VISUAL_TYPES:
        return FLUX_DIAGRAM_NEGATIVE_PROMPT
    return None
