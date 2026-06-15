"""Tests for agent.core.json_parse."""

from __future__ import annotations

from types import SimpleNamespace

import json
import pytest
from pydantic import BaseModel

from agent.core.json_parse import (
    extract_array_objects,
    is_json_parse_failure,
    parse_gemini_response,
    parse_json_text,
    repair_gemini_array_corruption,
    repair_truncated_json,
)


class _FakeBrief(BaseModel):
    subject_entity: str
    key_facts: list[str]


BROKEN_GEMINI_RESPONSE = """{
  "subject_entity": "Paradisier superbe (Lophorina superba)",
  "key_facts":.",
    "L'espèce présente un dimorphisme sexuel extrême",
    "Les plumes noires du mâle sont qualifiées de super-noires",
  "timeline": [{"year": "1930", "event": "Découverte"}],
  "sources": [{"title": "Wiki", "url": "https://x", "snippet": "s"}],
  "visual_anchors": ["plumage"],
  "common_misconceptions": ["m1"],
  "narrative_angles": ["a1"],
  "confidence": 0.9,
  "niche_risk": "low"
}"""


def test_parse_gemini_response_uses_parsed_dict() -> None:
    response = SimpleNamespace(parsed={"subject_entity": "Verdun", "key_facts": []}, text="")
    data = parse_gemini_response(response, "gemini-test")
    assert data["subject_entity"] == "Verdun"


def test_parse_gemini_response_uses_parsed_basemodel() -> None:
    response = SimpleNamespace(
        parsed=_FakeBrief(subject_entity="Verdun", key_facts=["fait"]),
        text="",
    )
    data = parse_gemini_response(response, "gemini-test")
    assert data["subject_entity"] == "Verdun"
    assert data["key_facts"] == ["fait"]


def test_parse_json_text_extracts_markdown_block() -> None:
    raw = """Voici le brief :
```json
{
  "subject_entity": "Verdun",
  "key_facts": ["1916"]
}
```"""
    data = parse_json_text(raw)
    assert data["subject_entity"] == "Verdun"


def test_parse_json_text_extracts_balanced_object() -> None:
    raw = 'Analyse :\n{"subject_entity": "Verdun", "key_facts": ["1916"]}\nMerci.'
    data = parse_json_text(raw)
    assert data["key_facts"] == ["1916"]


def test_parse_json_text_fixes_trailing_commas() -> None:
    raw = '{\n  "subject_entity": "Verdun",\n  "key_facts": ["1916",],\n}'
    data = parse_json_text(raw)
    assert data["key_facts"] == ["1916"]


def test_parse_json_text_repairs_gemini_array_corruption() -> None:
    data = parse_json_text(BROKEN_GEMINI_RESPONSE, "gemini-test")
    assert data["subject_entity"] == "Paradisier superbe (Lophorina superba)"
    assert len(data["key_facts"]) == 2
    assert data["confidence"] == 0.9


def test_repair_gemini_array_corruption() -> None:
    fixed = repair_gemini_array_corruption('"key_facts":.",\n  "a",')
    assert '"key_facts": [' in fixed
    assert '],' in fixed or fixed.endswith("]")


def test_parse_gemini_response_raises_value_error_with_snippet() -> None:
    response = SimpleNamespace(parsed=None, text='{"subject_entity": ,}')
    with pytest.raises(ValueError, match="JSON invalide"):
        parse_gemini_response(response, "gemini-test")


def test_parse_gemini_response_required_field_from_text() -> None:
    response = SimpleNamespace(parsed={"scores": "bad"}, text='{"scores": [{"index": 0}]}')
    data = parse_gemini_response(response, "gemini-test", required_field="scores")
    assert isinstance(data["scores"], list)


def test_is_json_parse_failure_detects_json_errors() -> None:
    assert is_json_parse_failure(ValueError("JSON invalide de gemini-test : {}")) is True
    assert is_json_parse_failure(RuntimeError("quota")) is False


def test_repair_truncated_json_closes_unterminated_string() -> None:
    raw = '{"segments": [{"order": 1, "narration_text": "Texte tronqu'
    repaired = repair_truncated_json(raw)
    data = json.loads(repaired)
    assert data["segments"][0]["order"] == 1


def test_repair_truncated_json_closes_scores_array() -> None:
    raw = """{
  "scores": [
    {
      "index": 0,
      "score": 70,
      "reason": "Montre la Tour de Pise et son inclinaison, mais pas la base ni le sol environnant.",
      "rejection_category": "ok"
    },"""
    data = parse_json_text(repair_truncated_json(raw))
    assert len(data["scores"]) == 1
    assert data["scores"][0]["score"] == 70


def test_extract_array_objects_recovers_complete_scores() -> None:
    raw = """{
  "scores": [
    {
      "index": 0,
      "score": 90,
      "reason": "L'image montre la tour de Pise, mais pas l'inclinaison ou les fondations.",
      "rejection_category": "ok"
    },
    {
      "index": 1,
      "score": 95,
      "reason": "Montre la tour de Pise et son inclinaison, mais """
    objects = extract_array_objects(raw, "scores")
    assert objects is not None
    assert len(objects) == 1
    assert objects[0]["index"] == 0


def test_parse_gemini_response_extracts_partial_scores() -> None:
    raw = """{
  "scores": [
    {
      "index": 0,
      "score": 70,
      "reason": "Montre la Tour de Pise",
      "rejection_category": "ok"
    },"""
    response = SimpleNamespace(parsed=None, text=raw)
    data = parse_gemini_response(response, "gemini-2.5-flash", required_field="scores")
    assert len(data["scores"]) == 1
    assert data["scores"][0]["score"] == 70


def test_parse_gemini_response_scalar_from_parsed() -> None:
    response = SimpleNamespace(
        parsed={"subject_en": "Leaning Tower foundations cross section"},
        text="",
    )
    data = parse_gemini_response(response, "gemini-test", required_field="subject_en")
    assert data["subject_en"] == "Leaning Tower foundations cross section"


def test_parse_gemini_response_scalar_from_text() -> None:
    response = SimpleNamespace(
        parsed=None,
        text='{"subject_en": "Educational diagram of soil layers with arrows"}',
    )
    data = parse_gemini_response(response, "gemini-test", required_field="subject_en")
    assert data["subject_en"] == "Educational diagram of soil layers with arrows"


def test_parse_gemini_response_scalar_rejects_empty() -> None:
    response = SimpleNamespace(parsed={"subject_en": ""}, text='{"subject_en": ""}')
    with pytest.raises(ValueError, match="champ subject_en absent"):
        parse_gemini_response(response, "gemini-test", required_field="subject_en")
