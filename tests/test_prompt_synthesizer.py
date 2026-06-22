from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from agent.skills.media_sources.ai.flux_negative_prompt import (
    FLUX_DIAGRAM_NEGATIVE_PROMPT,
    FLUX_PHOTO_NEGATIVE_PROMPT,
    flux_negative_prompt_for_visual_type,
)
from agent.skills.media_sources.ai.prompt_builder import build_visual_prompt
from agent.skills.media_sources.ai.prompt_synthesizer import (
    SearchAnchor,
    _synthesize_sync,
    _translate_anchor_sync,
    fallback_sanitize_subject,
    translate_search_anchor,
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


def test_translate_anchor_sync_parses_anchor_and_terms() -> None:
    mock_response = SimpleNamespace(
        parsed={"anchor_en": "Moai Easter Island", "terms_en": ["Rapa Nui", "Rano Raraku"]},
        text="",
    )
    mock_client = MagicMock()
    mock_client.models.generate_content.return_value = mock_response

    with patch("google.genai.Client", return_value=mock_client):
        anchor = _translate_anchor_sync(
            subject_entity="Moaï de l'île de Pâques (Rapa Nui)",
            must_include=[],
            api_key="test-key",
        )

    assert anchor.anchor_en == "moai easter island"  # normalisé en minuscules
    assert anchor.terms_en == ["rapa nui", "rano raraku"]
    assert anchor.is_usable


@pytest.mark.asyncio
async def test_translate_search_anchor_fallback_without_key() -> None:
    # Sans clé Gemini : on retombe sur l'entité brute (jamais de régression / crash).
    anchor = await translate_search_anchor(
        subject_entity="Moaï de l'île de Pâques",
        api_key=None,
        cache_dir=None,
    )
    assert isinstance(anchor, SearchAnchor)
    assert anchor.is_usable
    assert "moa" in anchor.anchor_en  # entité minusculisée conservée


@pytest.mark.asyncio
async def test_translate_search_anchor_empty_entity_is_unusable() -> None:
    anchor = await translate_search_anchor(subject_entity="", api_key=None)
    assert not anchor.is_usable
