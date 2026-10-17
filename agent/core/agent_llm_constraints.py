"""Modèles autorisés par fournisseur pour les agents Python restants (tâches texte uniquement)."""

from __future__ import annotations

from agent.core.llm_resolver import AgentLlmPreference, FREE_GEMINI_MODEL

ALLOWED_PROVIDERS: tuple[str, ...] = ("gemini", "anthropic", "claude_cli")

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
    "claude-opus-5-5",
    "claude-sonnet-5-5",
    "claude-haiku-4-5-20251001",
)
# Claude Code CLI (abonnement Claude, sans clé) : alternative à Gemini pour le texte.
CLAUDE_CLI_MODELS: tuple[str, ...] = (
    "claude-sonnet-5-5",
    "claude-opus-5-5",
    "claude-haiku-5-5",
)


def allowed_models(*, provider: str, tier: str) -> tuple[str, ...]:
    if provider == "anthropic":
        return ANTHROPIC_TEXT_MODELS
    if provider == "claude_cli":
        return CLAUDE_CLI_MODELS
    if provider == "gemini":
        return GEMINI_TEXT_PAID_MODELS if tier == "paid" else GEMINI_TEXT_FREE_MODELS
    return ()


def default_model(*, provider: str, tier: str) -> str:
    models = allowed_models(provider=provider, tier=tier)
    return models[0] if models else FREE_GEMINI_MODEL


def normalize_preference(pref: AgentLlmPreference) -> AgentLlmPreference:
    """Force un fournisseur, un tier et un modèle cohérents entre eux."""
    provider = pref.provider if pref.provider in ALLOWED_PROVIDERS else ALLOWED_PROVIDERS[0]
    if provider == "anthropic":
        tier = "paid"
    elif provider == "claude_cli":
        tier = "free"
    else:
        tier = pref.tier if pref.tier in ("free", "paid") else "free"
    models = allowed_models(provider=provider, tier=tier)
    model = pref.model if pref.model in models else default_model(provider=provider, tier=tier)
    return AgentLlmPreference(provider=provider, model=model, tier=tier)  # type: ignore[arg-type]


def normalize_preferences_map(
    prefs: dict[str, AgentLlmPreference],
) -> dict[str, AgentLlmPreference]:
    return {agent_name: normalize_preference(pref) for agent_name, pref in prefs.items()}
