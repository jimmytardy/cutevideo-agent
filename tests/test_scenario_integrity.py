from __future__ import annotations

import uuid

import pytest

from agent.core.channel_config import ChannelRuntimeConfig
from agent.core.database import Scenario
from agent.core.scenario_integrity import (
    scenario_expects_narration,
    validate_merged_segments,
    validate_scenario_integrity,
    validate_segment_count_preserved,
)


def _valid_segment(order: int) -> dict:
    return {
        "order": order,
        "duration_s": 30,
        "needs_voice": True,
        "needs_music": True,
        "narration_text": f"Narration segment {order}.",
        "visual_beats": [
            {
                "order": 1,
                "phrase_anchor": "intro",
                "visual_type": "documentary_photo",
            }
        ],
    }


def test_validate_segment_count_preserved_accepts_same_count() -> None:
    original = [_valid_segment(1), _valid_segment(2)]
    validate_segment_count_preserved(original, list(original), context="test")


def test_validate_segment_count_preserved_rejects_truncation() -> None:
    original = [_valid_segment(1), _valid_segment(2)]
    with pytest.raises(ValueError, match="test"):
        validate_segment_count_preserved(original, [_valid_segment(1)], context="test")


def test_validate_merged_segments_rejects_erased_narration() -> None:
    original = [_valid_segment(1)]
    corrupted = [
        {
            "order": 1,
            "title": "Sans narration",
            "visual_beats": original[0]["visual_beats"],
        }
    ]
    with pytest.raises(ValueError, match="narration_text"):
        validate_merged_segments(original, corrupted)


def test_validate_merged_segments_accepts_valid_merge() -> None:
    from agent.agents.diagram_specialist_agent import merge_diagram_enrichment

    original = [_valid_segment(1)]
    llm = [
        {
            "order": 1,
            "visual_beats": [
                {
                    "order": 1,
                    "phrase_anchor": "intro",
                    "visual_type": "scientific_diagram",
                    "prompt": "Diagramme enrichi",
                }
            ],
        }
    ]
    merged = merge_diagram_enrichment(original, llm)
    validate_merged_segments(original, merged)


def test_validate_scenario_integrity_rejects_truncated_scenario() -> None:
    truncated = [
        {
            "order": 1,
            "title": "Hook",
            "visual_beats": [
                {
                    "order": 1,
                    "phrase_anchor": "Et pourtant, elle pèse 14 500 tonnes !",
                    "visual_type": "statistic_highlight",
                }
            ],
        }
    ]
    scenario = Scenario(
        project_id=uuid.uuid4(),
        segments=truncated,
        total_duration_s=60,
    )
    cfg = ChannelRuntimeConfig(production_mode="mixed")

    with pytest.raises(RuntimeError, match="narration_text"):
        validate_scenario_integrity(scenario, cfg)


def test_validate_scenario_integrity_accepts_valid_scenario() -> None:
    scenario = Scenario(
        project_id=uuid.uuid4(),
        segments=[_valid_segment(1), _valid_segment(2)],
        total_duration_s=60,
    )
    cfg = ChannelRuntimeConfig(production_mode="mixed")
    validate_scenario_integrity(scenario, cfg)


def test_scenario_expects_narration_with_phrase_anchor_only() -> None:
    segments = [
        {
            "order": 1,
            "visual_beats": [{"order": 1, "phrase_anchor": "anchor", "visual_type": "photo"}],
        }
    ]
    assert scenario_expects_narration(segments) is True


def test_scenario_expects_narration_false_when_empty() -> None:
    segments = [{"order": 1, "needs_voice": False, "visual_beats": []}]
    assert scenario_expects_narration(segments) is False
