"""Tests alignement short_producer sur pipeline post-TTS."""

from __future__ import annotations

from agent.agents.short_producer_agent import (
    DERIVATION_PROMPT,
    clamp_short_total_duration,
    postprocess_derivation_segments,
)
from agent.core.channel_config import VisualBeatsConfig


def test_derivation_prompt_uses_min_max_range() -> None:
    prompt = DERIVATION_PROMPT.format(
        min_duration_s=60,
        max_duration_s=120,
        target_duration_s=90,
        segment_duration=20,
        channel_name="Test",
        theme_category="science",
        theme="Sujet",
        creative_brief_block="",
        planned_short_block="",
        segments_json="[]",
        research_block="",
        learning_block="",
        research_rules_block="",
        sources_block="",
        visual_beats_rules="NE PAS GÉNÉRER visual_beats",
    )
    assert "60 à 120" in prompt
    assert "60–120 s" in prompt
    assert "NE PAS GÉNÉRER visual_beats" in prompt


def test_postprocess_strips_visual_beats_from_voice_segments() -> None:
    raw = [
        {
            "order": 1,
            "needs_voice": True,
            "narration_text": "Hook percutant",
            "visual_beats": [{"order": 1, "visual_type": "documentary_photo"}],
        },
    ]
    vb = VisualBeatsConfig()
    segments = postprocess_derivation_segments(
        raw,
        min_beats=3,
        max_beats=6,
        editorial_tone="educational",
        theme_category="science",
        vb_config=vb,
    )
    assert "visual_beats" not in segments[0]


def test_clamp_short_total_duration() -> None:
    assert clamp_short_total_duration(150, min_duration_s=60, max_duration_s=120, fallback=90) == 120
    assert clamp_short_total_duration(40, min_duration_s=60, max_duration_s=120, fallback=90) == 60
    assert clamp_short_total_duration(None, min_duration_s=60, max_duration_s=120, fallback=90) == 90
