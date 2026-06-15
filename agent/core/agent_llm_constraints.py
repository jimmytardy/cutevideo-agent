from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from agent.core.llm_resolver import (
    AgentLlmPreference,
    FREE_GEMINI_MODEL,
    LLM_PREFERENCE_ALIAS,
    preference_agent_name,
)

AgentTaskKind = Literal["text", "vision", "gemini_search"]

GEMINI_TEXT_FREE_MODELS: tuple[str, ...] = (
    "gemini-2.5-flash-lite",
    "gemini-2.5-flash",
)
GEMINI_TEXT_PAID_MODELS: tuple[str, ...] = (
    "gemini-2.5-flash",
    "gemini-2.5-pro",
    "gemini-3.5-flash",
    "gemini-3.1-pro-preview",
)
ANTHROPIC_TEXT_MODELS: tuple[str, ...] = (
    "claude-opus-4-5",
    "claude-sonnet-4-5",
    "claude-haiku-4-5-20251001",
)

GEMINI_VISION_FREE_MODELS: tuple[str, ...] = ("gemini-2.5-flash",)
GEMINI_VISION_PAID_MODELS: tuple[str, ...] = (
    "gemini-2.5-flash",
    "gemini-2.5-pro",
    "gemini-3.5-flash",
    "gemini-3.1-pro-preview",
)

GEMINI_SEARCH_FREE_MODELS: tuple[str, ...] = (
    "gemini-2.5-flash",
    "gemini-3.5-flash",
)
GEMINI_SEARCH_PAID_MODELS: tuple[str, ...] = (
    "gemini-2.5-flash",
    "gemini-2.5-pro",
    "gemini-3.5-flash",
    "gemini-3.1-pro-preview",
)

_AGENT_TASK_KIND: dict[str, AgentTaskKind] = {
    "media_agent_llm": "vision",
    "research_agent": "gemini_search",
}


@dataclass(frozen=True)
class AgentLlmConstraint:
    task_kind: AgentTaskKind
    allowed_providers: tuple[str, ...]


def agent_task_kind(agent_name: str) -> AgentTaskKind:
    source = preference_agent_name(agent_name)
    return _AGENT_TASK_KIND.get(source, "text")


def agent_llm_constraint(agent_name: str) -> AgentLlmConstraint:
    kind = agent_task_kind(agent_name)
    if kind in ("vision", "gemini_search"):
        return AgentLlmConstraint(task_kind=kind, allowed_providers=("gemini",))
    return AgentLlmConstraint(task_kind="text", allowed_providers=("gemini", "anthropic"))


def gemini_models_for_task(kind: AgentTaskKind, *, tier: str) -> tuple[str, ...]:
    paid = tier == "paid"
    if kind == "vision":
        return GEMINI_VISION_PAID_MODELS if paid else GEMINI_VISION_FREE_MODELS
    if kind == "gemini_search":
        return GEMINI_SEARCH_PAID_MODELS if paid else GEMINI_SEARCH_FREE_MODELS
    return GEMINI_TEXT_PAID_MODELS if paid else GEMINI_TEXT_FREE_MODELS


def allowed_models_for_agent(
    agent_name: str,
    *,
    provider: str,
    tier: str,
) -> tuple[str, ...]:
    kind = agent_task_kind(agent_name)
    if provider == "anthropic":
        return ANTHROPIC_TEXT_MODELS if kind == "text" else ()
    if provider == "gemini":
        return gemini_models_for_task(kind, tier=tier)
    return ()


def default_model_for_agent(agent_name: str, *, provider: str, tier: str) -> str:
    models = allowed_models_for_agent(agent_name, provider=provider, tier=tier)
    if models:
        return models[0]
    if provider == "gemini":
        return FREE_GEMINI_MODEL
    return ANTHROPIC_TEXT_MODELS[0]


def normalize_agent_preference(agent_name: str, pref: AgentLlmPreference) -> AgentLlmPreference:
    """Force fournisseur/modèle cohérents avec les capacités réelles de l'agent."""
    constraint = agent_llm_constraint(agent_name)
    provider = pref.provider if pref.provider in constraint.allowed_providers else constraint.allowed_providers[0]
    if provider == "anthropic":
        tier = "paid"
    else:
        tier = pref.tier if pref.tier in ("free", "paid") else "free"
    models = allowed_models_for_agent(agent_name, provider=provider, tier=tier)
    model = pref.model if pref.model in models else default_model_for_agent(
        agent_name, provider=provider, tier=tier
    )
    return AgentLlmPreference(provider=provider, model=model, tier=tier)  # type: ignore[arg-type]


def normalize_preferences_map(
    prefs: dict[str, AgentLlmPreference],
) -> dict[str, AgentLlmPreference]:
    out: dict[str, AgentLlmPreference] = {}
    for agent_name, pref in prefs.items():
        out[agent_name] = normalize_agent_preference(agent_name, pref)
    return out


def linked_agents_for_api() -> dict[str, str]:
    return dict(LLM_PREFERENCE_ALIAS)
