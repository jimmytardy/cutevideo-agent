"""Tests contraintes modèles LLM par agent."""

from __future__ import annotations

from agent.core.agent_llm_constraints import (
    allowed_models_for_agent,
    normalize_agent_preference,
)
from agent.core.llm_resolver import AgentLlmPreference


def test_media_agent_llm_rejects_anthropic() -> None:
    pref = normalize_agent_preference(
        "media_agent_llm",
        AgentLlmPreference(provider="anthropic", model="claude-opus-4-5", tier="paid"),
    )
    assert pref.provider == "gemini"
    assert pref.model == "gemini-2.5-flash"


def test_media_agent_llm_rejects_flash_lite() -> None:
    pref = normalize_agent_preference(
        "media_agent_llm",
        AgentLlmPreference(provider="gemini", model="gemini-2.5-flash-lite", tier="free"),
    )
    assert pref.model == "gemini-2.5-flash"


def test_media_agent_llm_allows_vision_paid_models() -> None:
    models = allowed_models_for_agent(
        "media_agent_llm", provider="gemini", tier="paid"
    )
    assert "gemini-2.5-pro" in models
    assert "gemini-2.5-flash-lite" not in models
    assert "claude-opus-4-5" not in allowed_models_for_agent(
        "media_agent_llm", provider="anthropic", tier="paid"
    )


def test_research_agent_gemini_only_with_search_models() -> None:
    pref = normalize_agent_preference(
        "research_agent",
        AgentLlmPreference(provider="anthropic", model="claude-sonnet-4-5", tier="paid"),
    )
    assert pref.provider == "gemini"
    free_models = allowed_models_for_agent("research_agent", provider="gemini", tier="free")
    assert "gemini-3.5-flash" in free_models
    assert "gemini-2.5-flash-lite" not in free_models


def test_text_agent_keeps_anthropic() -> None:
    pref = normalize_agent_preference(
        "scenario_agent",
        AgentLlmPreference(provider="anthropic", model="claude-opus-4-5", tier="paid"),
    )
    assert pref.provider == "anthropic"
    assert pref.model == "claude-opus-4-5"


def test_resolve_scoring_model_chain_prioritizes_user_model() -> None:
    from agent.skills.media_sources.relevance_scorer import resolve_scoring_model_chain

    chain = resolve_scoring_model_chain("gemini-2.5-pro")
    assert chain[0] == "gemini-2.5-pro"
    assert "gemini-2.5-flash" in chain
