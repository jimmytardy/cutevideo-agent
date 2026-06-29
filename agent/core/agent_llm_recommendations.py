from __future__ import annotations

from agent.core.llm_resolver import preference_agent_name

MODEL_DISPLAY: dict[str, str] = {
    "gemini-2.5-flash-lite": "Gemini 2.5 Flash Lite",
    "gemini-2.5-flash": "Gemini 2.5 Flash",
    "gemini-2.5-pro": "Gemini 2.5 Pro",
    "gemini-3.5-flash": "Gemini 3.5 Flash",
    "gemini-3.1-pro-preview": "Gemini 3.1 Pro Preview",
    "claude-opus-4-5": "Claude Opus 4.5",
    "claude-sonnet-4-5": "Claude Sonnet 4.5",
    "claude-haiku-4-5-20251001": "Claude Haiku 4.5",
}

# Modèle unique conseillé par agent (aligné sur l'usage principal dans le code).
_AGENT_RECOMMENDED: dict[str, str] = {
    "research_agent": "gemini-3.5-flash",
    "scenario_agent": "claude-opus-4-5",
    "fact_checker_agent": "claude-opus-4-5",
    "montage_planner_agent": "claude-opus-4-5",
    "hook_optimizer_agent": "claude-opus-4-5",
    "diagram_specialist_agent": "claude-opus-4-5",
    "critic_agent": "claude-sonnet-4-5",
    "content_planner_agent": "claude-sonnet-4-5",
    "clipper_agent": "claude-opus-4-5",
    "short_producer_agent": "claude-opus-4-5",
    "comments_agent": "claude-sonnet-4-5",
    "channel_planner_agent": "claude-opus-4-5",
    "style_director_agent": "gemini-2.5-pro",
    "distribution_agent": "claude-sonnet-4-5",
    "scenario_media_gap": "claude-sonnet-4-5",
    "validation_brief": "claude-opus-4-5",
    "source_advisor": "claude-haiku-4-5-20251001",
    "media_agent_llm": "gemini-2.5-flash",
}


def _display_model(model_id: str) -> str:
    return MODEL_DISPLAY.get(model_id, model_id)


def _default_recommended_model(agent_name: str) -> str:
    from agent.core.llm_config import resolve_model

    return resolve_model(preference_agent_name(agent_name))


def recommended_llm_label(agent_name: str) -> str:
    """Libellé court du modèle conseillé pour l'UI de configuration."""
    source = preference_agent_name(agent_name)
    model_id = _AGENT_RECOMMENDED.get(source, _default_recommended_model(agent_name))
    return _display_model(model_id)


def all_agent_llm_recommendations(agent_names: list[str]) -> dict[str, str]:
    return {name: recommended_llm_label(name) for name in agent_names}
