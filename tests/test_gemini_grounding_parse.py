"""Tests parsing Gemini research payloads."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from agent.core.json_parse import is_json_parse_failure
from agent.skills.research.gemini_grounding import _call_research_model


def test_is_parse_failure_detects_json_errors() -> None:
    assert is_json_parse_failure(ValueError("JSON invalide de gemini-test : {}")) is True
    assert is_json_parse_failure(RuntimeError("quota")) is False


def test_call_research_model_reformats_on_parse_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    broken_text = '{"subject_entity": ,}'
    fake_response = SimpleNamespace(parsed=None, text=broken_text)
    reformat_calls: list[str] = []

    fake_client = SimpleNamespace(
        models=SimpleNamespace(generate_content=lambda **kwargs: fake_response)
    )
    fake_types = SimpleNamespace(
        Tool=lambda **kwargs: object(),
        GoogleSearch=lambda: object(),
        GenerateContentConfig=lambda **kwargs: object(),
    )

    def fake_reformat(
        client: object,
        types: object,
        raw: str,
        reformat_model: str,
    ) -> dict[str, object]:
        reformat_calls.append(reformat_model)
        assert raw == broken_text
        return {"subject_entity": "Verdun", "key_facts": ["1916"]}

    monkeypatch.setattr(
        "agent.skills.research.gemini_grounding._reformat_research_json",
        fake_reformat,
    )

    data = _call_research_model(
        fake_client,
        fake_types,
        "gemini-3.5-flash",
        "prompt",
        reformat_model="gemini-2.5-flash-lite",
    )
    assert data["subject_entity"] == "Verdun"
    assert data["key_facts"] == ["1916"]
    assert reformat_calls == ["gemini-2.5-flash-lite"]
