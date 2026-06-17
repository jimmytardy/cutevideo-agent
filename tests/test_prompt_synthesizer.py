from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from agent.skills.media_sources.ai.flux_negative_prompt import (
    FLUX_DIAGRAM_NEGATIVE_PROMPT,
    FLUX_PHOTO_NEGATIVE_PROMPT,
    flux_negative_prompt_for_visual_type,
)
from agent.skills.media_sources.ai.prompt_builder import build_visual_prompt
from agent.skills.media_sources.ai.prompt_synthesizer import (
    _synthesize_sync,
    fallback_sanitize_subject,
)
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


def test_flux_negative_prompt_by_visual_type() -> None:
    assert flux_negative_prompt_for_visual_type("scientific_diagram") == FLUX_DIAGRAM_NEGATIVE_PROMPT
    # A3 — les photos reçoivent désormais un négatif qualité (anatomie/artefacts).
    assert flux_negative_prompt_for_visual_type("documentary_photo") == FLUX_PHOTO_NEGATIVE_PROMPT


def test_is_text_artifact_rejection() -> None:
    assert is_text_artifact_rejection("text_artifact")
    assert is_text_artifact_rejection("ok", "Labels illisibles dans l'image")
    assert not is_text_artifact_rejection("ok", "Concept pertinent")


def test_synthesize_sync_parses_scalar_subject_en() -> None:
    mock_response = SimpleNamespace(
        parsed={"subject_en": "Cross section of tower foundations in sandy soil"},
        text="",
    )
    mock_client = MagicMock()
    mock_client.models.generate_content.return_value = mock_response

    with patch("google.genai.Client", return_value=mock_client):
        result = _synthesize_sync(
            visual_type="scientific_diagram",
            prompt_fr="Diagramme des fondations de la tour dans le sol meuble.",
            style_hint="educational style",
            phrase_anchor="sol meuble",
            api_key="test-key",
        )

    assert result == "Cross section of tower foundations in sandy soil"
    mock_client.models.generate_content.assert_called_once()
