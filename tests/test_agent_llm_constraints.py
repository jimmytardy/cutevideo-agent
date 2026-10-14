"""Tests contraintes modèles LLM par agent."""

from __future__ import annotations

from agent.core.agent_llm_constraints import (
    normalize_agent_preference,
)
from agent.core.llm_resolver import AgentLlmPreference


def test_text_agent_keeps_anthropic() -> None:
    pref = normalize_agent_preference(
        "scenario_agent",
        AgentLlmPreference(provider="anthropic", model="claude-opus-5-5", tier="paid"),
    )
    assert pref.provider == "anthropic"
    assert pref.model == "claude-opus-5-5"
