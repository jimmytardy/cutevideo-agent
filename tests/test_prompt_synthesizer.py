from __future__ import annotations

from agent.skills.media_sources.ai.flux_negative_prompt import (
    FLUX_DIAGRAM_NEGATIVE_PROMPT,
    flux_negative_prompt_for_visual_type,
)
from agent.skills.media_sources.ai.prompt_builder import build_visual_prompt
from agent.skills.media_sources.ai.prompt_synthesizer import fallback_sanitize_subject
from agent.skills.media_sources.relevance_scorer import is_text_artifact_rejection


def test_fallback_sanitize_subject_strips_label_instructions() -> None:
    prompt_fr = (
        "Diagramme explicatif montrant le sol meuble. "
        "Les labels indiquent clairement le poids et la profondeur."
    )
    result = fallback_sanitize_subject(prompt_fr)
    assert "labels" not in result.lower()
    assert "indiquent" not in result.lower()
    assert "sol meuble" in result.lower() or "Diagramme" in result


def test_build_visual_prompt_diagram_no_empty_zones() -> None:
    prompt = build_visual_prompt("scientific_diagram", "tower foundations cross section")
    lower = prompt.lower()
    assert "no text" in lower
    assert "empty zones" not in lower
    assert "text placeholders" in lower or "annotation areas" in lower


def test_flux_negative_prompt_for_diagram_only() -> None:
    assert flux_negative_prompt_for_visual_type("scientific_diagram") == FLUX_DIAGRAM_NEGATIVE_PROMPT
    assert flux_negative_prompt_for_visual_type("documentary_photo") is None


def test_is_text_artifact_rejection() -> None:
    assert is_text_artifact_rejection("text_artifact")
    assert is_text_artifact_rejection("ok", "Labels illisibles dans l'image")
    assert not is_text_artifact_rejection("ok", "Concept pertinent")
