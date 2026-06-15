from __future__ import annotations

import pytest

from agent.agents.diagram_specialist_agent import merge_diagram_enrichment
from agent.core.scenario_integrity import validate_merged_segments


def _base_segment(order: int) -> dict:
    return {
        "order": order,
        "title": f"Segment {order}",
        "duration_s": 20,
        "needs_voice": True,
        "needs_music": True,
        "narration_text": f"Narration complète du segment {order}.",
        "on_screen_text": f"Écran {order}",
        "delivery_style": {"pace": "medium", "emotion": "calm"},
        "visual_beats": [
            {
                "order": 1,
                "phrase_anchor": "photo intro",
                "visual_type": "battle_map",
                "prompt": "Carte originale",
            },
            {
                "order": 2,
                "phrase_anchor": "diagramme clé",
                "visual_type": "scientific_diagram",
                "prompt": "Diagramme original",
            },
        ],
    }


def test_merge_preserves_all_segments_and_narration_when_llm_truncates() -> None:
    original = [_base_segment(1), _base_segment(2), _base_segment(3)]
    llm_response = [
        {
            "order": 2,
            "visual_beats": [
                {
                    "order": 2,
                    "phrase_anchor": "diagramme clé",
                    "visual_type": "scientific_diagram",
                    "prompt": "Diagramme enrichi segment 2",
                    "diagram_brief": {"layout": "coupe", "key_elements": ["sol"]},
                }
            ],
        },
        {
            "order": 3,
            "visual_beats": [
                {
                    "order": 2,
                    "phrase_anchor": "diagramme clé",
                    "visual_type": "scientific_diagram",
                    "prompt": "Diagramme enrichi segment 3",
                    "diagram_brief": {"layout": "jauge", "key_elements": ["angle"]},
                }
            ],
        },
    ]

    merged = merge_diagram_enrichment(original, llm_response)

    assert len(merged) == 3
    assert merged[0]["narration_text"] == "Narration complète du segment 1."
    assert merged[0]["needs_voice"] is True
    assert merged[1]["narration_text"] == "Narration complète du segment 2."
    assert merged[2]["needs_music"] is True


def test_merge_enriches_only_diagram_beats() -> None:
    original = [_base_segment(1)]
    llm_response = [
        {
            "order": 1,
            "visual_beats": [
                {
                    "order": 2,
                    "phrase_anchor": "diagramme clé",
                    "visual_type": "scientific_diagram",
                    "prompt": "Diagramme enrichi",
                    "diagram_labels": [{"text": "Sol", "role": "label"}],
                    "diagram_brief": {"layout": "coupe", "key_elements": ["sol"]},
                }
            ],
        }
    ]

    merged = merge_diagram_enrichment(original, llm_response)
    beats = merged[0]["visual_beats"]

    assert beats[0]["visual_type"] == "battle_map"
    assert beats[0]["prompt"] == "Carte originale"
    assert beats[1]["prompt"] == "Diagramme enrichi"
    assert beats[1]["diagram_brief"]["layout"] == "coupe"


def test_merge_keeps_original_when_llm_returns_empty_segments() -> None:
    original = [_base_segment(1), _base_segment(2)]
    merged = merge_diagram_enrichment(original, [])
    assert merged == original


def test_validate_merged_segments_rejects_changed_needs_voice() -> None:
    original = [_base_segment(1)]
    bad = [dict(original[0], needs_voice=None)]
    with pytest.raises(ValueError, match="needs_voice"):
        validate_merged_segments(original, bad)
