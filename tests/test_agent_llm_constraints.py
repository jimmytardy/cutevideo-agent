"""Tests de cohérence fournisseur / tier / modèle des préférences LLM."""

from __future__ import annotations

from agent.core.agent_llm_constraints import GEMINI_TEXT_FREE_MODELS, normalize_preference
from agent.core.llm_resolver import AgentLlmPreference


def test_anthropic_preference_is_kept() -> None:
    pref = normalize_preference(AgentLlmPreference(provider="anthropic", model="claude-opus-5-5", tier="paid"))
    assert (pref.provider, pref.model, pref.tier) == ("anthropic", "claude-opus-5-5", "paid")


def test_unknown_model_falls_back_to_provider_default() -> None:
    pref = normalize_preference(AgentLlmPreference(provider="gemini", model="gemini-3.1-pro-preview", tier="free"))
    assert (pref.provider, pref.model, pref.tier) == ("gemini", GEMINI_TEXT_FREE_MODELS[0], "free")
