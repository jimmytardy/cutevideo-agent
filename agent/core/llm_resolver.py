from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass
from typing import Any, Literal

from sqlalchemy.ext.asyncio import AsyncSession

from agent.core.api_keys import GcpCredentials, parse_gcp_credentials, resolve_api_key
from agent.core.database import User
from agent.core.llm_config import resolve_max_tokens, resolve_model
from agent.core.llm_retry import retry_transient_async

logger = logging.getLogger(__name__)

# Nombre de relances de continuation lorsqu'une réponse est coupée par max_tokens.
# Chaque continuation reprend là où le modèle s'est arrêté (prefill Anthropic /
# tour de continuation Gemini) ; au-delà du cap on renvoie le texte accumulé en
# best-effort (le filet de réparation JSON côté agent prend le relais).
MAX_CONTINUATIONS = 4

LlmProvider = Literal["gemini", "anthropic"]
LlmTier = Literal["free", "paid"]

FREE_GEMINI_MODEL = "gemini-2.5-flash-lite"
DEFAULT_FREE_GEMINI_MODEL = "gemini-2.5-flash"
PAID_GEMINI_MODELS: frozenset[str] = frozenset(
    {"gemini-2.5-pro", "gemini-2.5-flash", "gemini-3.1-pro-preview", "gemini-3.5-flash"}
)

CONFIGURABLE_AGENTS: frozenset[str] = frozenset(
    {
        "research_agent",
        "scenario_agent",
        "critic_agent",
        "content_planner_agent",
        "clipper_agent",
        "short_producer_agent",
        "comments_agent",
        "channel_planner_agent",
        "distribution_agent",
        "scenario_media_gap",
        "validation_brief",
        "source_advisor",
        "media_agent_llm",
    }
)

# Agents dont la config LLM est héritée d'un autre agent configurable.
LLM_PREFERENCE_ALIAS: dict[str, str] = {
    "outline_agent": "scenario_agent",
    "revision_agent": "scenario_agent",
    "fact_checker_agent": "scenario_agent",
    "montage_planner_agent": "scenario_agent",
    "hook_optimizer_agent": "scenario_agent",
    "diagram_specialist_agent": "scenario_agent",
    "beat_planner_agent": "scenario_agent",
}


def preference_agent_name(agent_name: str) -> str:
    return LLM_PREFERENCE_ALIAS.get(agent_name, agent_name)


@dataclass
class LlmCallConfig:
    provider: LlmProvider
    model: str
    api_key: str
    tier: LlmTier
    source: str
    # Quand True, l'appel Gemini passe par Vertex AI (auth compte de service GCP)
    # au lieu de l'API Gemini Developer (clé AIza). api_key est alors ignoré.
    use_vertex: bool = False
    gcp: GcpCredentials | None = None


@dataclass
class AgentLlmPreference:
    provider: LlmProvider = "gemini"
    model: str = FREE_GEMINI_MODEL
    tier: LlmTier = "free"


def parse_agent_preferences(raw: dict | None) -> dict[str, AgentLlmPreference]:
    if not raw:
        return {}
    out: dict[str, AgentLlmPreference] = {}
    for agent_name, cfg in raw.items():
        if not isinstance(cfg, dict):
            continue
        provider = cfg.get("provider", "gemini")
        if provider not in ("gemini", "anthropic"):
            provider = "gemini"
        tier = cfg.get("tier", "free")
        if tier not in ("free", "paid"):
            tier = "free"
        model = str(cfg.get("model", FREE_GEMINI_MODEL))
        out[str(agent_name)] = AgentLlmPreference(
            provider=provider,  # type: ignore[arg-type]
            model=model,
            tier=tier,  # type: ignore[arg-type]
        )
    return out


async def _has_user_key(session: AsyncSession, user_id: uuid.UUID, provider: str) -> bool:
    ctx = await resolve_api_key(session, user_id, provider, purpose="llm_agent", tier="paid")
    return ctx.source == "user" and bool(ctx.key)


async def _resolve_gcp_for_vertex(
    session: AsyncSession, user_id: uuid.UUID | None
) -> GcpCredentials | None:
    """Credentials GCP (compte de service) pour servir Gemini via Vertex AI.

    Contourne la restriction des clés AQ. de l'API Gemini Developer : Vertex
    s'authentifie via le compte de service, pas via une clé AIza.
    """
    ctx = await resolve_api_key(session, user_id, "gcp", purpose="llm_agent", tier="paid")
    if not ctx.key:
        return None
    return parse_gcp_credentials(ctx)


def _is_anthropic_model(model: str) -> bool:
    return model.startswith("claude-")


def _is_gemini_model(model: str) -> bool:
    return model.startswith("gemini-")


def _resolve_gemini_model(
    agent_name: str,
    *,
    pref: AgentLlmPreference | None,
    model_override: str | None,
    tier: LlmTier,
) -> str:
    """Retourne un modèle Gemini valide pour l'agent (jamais un identifiant Claude)."""
    from agent.core.agent_llm_constraints import allowed_models_for_agent, normalize_agent_preference

    normalized = normalize_agent_preference(
        agent_name,
        AgentLlmPreference(
            provider="gemini",
            model=pref.model if pref else FREE_GEMINI_MODEL,
            tier=tier,
        ),
    )
    if model_override and _is_gemini_model(model_override):
        allowed = allowed_models_for_agent(agent_name, provider="gemini", tier=tier)
        if model_override in allowed:
            return model_override
    return normalized.model


async def resolve_llm_call(
    session: AsyncSession,
    user: User | None,
    agent_name: str,
    *,
    model_override: str | None = None,
    tier_override: LlmTier | None = None,
) -> LlmCallConfig:
    """Résout provider/modèle/clé pour un appel LLM agent."""
    user_id = user.id if user else None
    config_agent = preference_agent_name(agent_name)
    prefs = parse_agent_preferences(user.agent_llm_preferences if user else None)
    pref = prefs.get(config_agent)

    has_anthropic = user_id is not None and await _has_user_key(session, user_id, "anthropic")
    has_gemini_user = user_id is not None and await _has_user_key(session, user_id, "gemini")

    config_default = resolve_model(config_agent)
    requested_model = model_override or (pref.model if pref else None) or config_default
    wants_anthropic = _is_anthropic_model(requested_model) or (
        pref is not None and pref.provider == "anthropic"
    )

    if wants_anthropic and has_anthropic:
        ctx = await resolve_api_key(session, user_id, "anthropic", purpose="llm_agent", tier="paid")
        if ctx.key:
            anthropic_model = (
                requested_model
                if _is_anthropic_model(requested_model)
                else config_default
            )
            return LlmCallConfig(
                provider="anthropic",
                model=anthropic_model,
                api_key=ctx.key,
                tier="paid",
                source=ctx.source,
            )

    if pref and has_gemini_user:
        tier: LlmTier = tier_override or pref.tier
        model = _resolve_gemini_model(
            config_agent,
            pref=pref,
            model_override=model_override,
            tier=tier,
        )
        ctx = await resolve_api_key(session, user_id, "gemini", purpose="llm_agent", tier=tier)
        if ctx.key:
            return LlmCallConfig(
                provider="gemini",
                model=model,
                api_key=ctx.key,
                tier=tier,
                source=ctx.source,
            )

    # Défaut : Gemini via Vertex AI (compte de service GCP) si configuré, sinon
    # clé Gemini Developer (user ou plateforme). Vertex est préféré car il évite
    # la restriction des clés AQ. de l'API Gemini Developer.
    tier = "free"
    model = _resolve_gemini_model(
        config_agent,
        pref=pref,
        model_override=model_override,
        tier=tier,
    )
    gcp = await _resolve_gcp_for_vertex(session, user_id)
    if gcp is not None:
        return LlmCallConfig(
            provider="gemini",
            model=model,
            api_key="",
            tier="free",
            source="vertex",
            use_vertex=True,
            gcp=gcp,
        )
    ctx = await resolve_api_key(session, user_id, "gemini", purpose="llm_agent", tier="free")
    if not ctx.key:
        raise RuntimeError(
            "Aucune clé Gemini disponible. Configurez Vertex AI (GCP_PROJECT_ID + "
            "GOOGLE_APPLICATION_CREDENTIALS), GOOGLE_GEMINI_API_KEY côté plateforme, "
            "ou ajoutez votre clé Gemini dans les paramètres compte."
        )
    return LlmCallConfig(
        provider="gemini",
        model=model,
        api_key=ctx.key,
        tier="free",
        source=ctx.source,
    )


async def call_llm(
    session: AsyncSession,
    user: User | None,
    agent_name: str,
    prompt: str,
    *,
    system: str | None = None,
    max_tokens: int | None = None,
    cacheable_context: str | None = None,
    model_override: str | None = None,
) -> str:
    cfg = await resolve_llm_call(session, user, agent_name, model_override=model_override)
    resolved_max = resolve_max_tokens(agent_name, max_tokens)

    if cfg.provider == "anthropic":
        import anthropic

        client = anthropic.AsyncAnthropic(api_key=cfg.api_key)
        user_content: list[dict[str, Any]] = []
        if cacheable_context and cacheable_context.strip():
            user_content.append(
                {
                    "type": "text",
                    "text": cacheable_context.strip(),
                    "cache_control": {"type": "ephemeral"},
                }
            )
        user_content.append({"type": "text", "text": prompt})
        kwargs: dict[str, Any] = {
            "model": cfg.model,
            "max_tokens": resolved_max,
            "messages": [{"role": "user", "content": user_content}],
        }
        if system and system.strip():
            kwargs["system"] = [
                {"type": "text", "text": system.strip(), "cache_control": {"type": "ephemeral"}}
            ]
        return await _anthropic_complete(client, kwargs, agent_name)

    return await _call_gemini_text(
        api_key=cfg.api_key,
        model=cfg.model,
        prompt=prompt,
        system=system,
        max_tokens=resolved_max,
        cacheable_context=cacheable_context,
        agent_name=agent_name,
        use_vertex=cfg.use_vertex,
        gcp=cfg.gcp,
    )


def _anthropic_text(response: Any) -> str:
    """Concatène tous les blocs texte d'une réponse Anthropic."""
    return "".join(
        block.text for block in response.content if getattr(block, "type", None) == "text"
    )


async def _anthropic_complete(client: Any, kwargs: dict[str, Any], agent_name: str) -> str:
    """Appel Anthropic avec continuation automatique si coupé par max_tokens.

    La continuation utilise le *prefill* : on renvoie le texte déjà produit comme
    dernier tour assistant, et l'API poursuit exactement où elle s'était arrêtée.
    """
    base_messages = list(kwargs["messages"])
    response = await retry_transient_async(
        lambda: client.messages.create(**kwargs), label=f"{agent_name}/anthropic"
    )
    text = _anthropic_text(response)

    continuations = 0
    while response.stop_reason == "max_tokens" and continuations < MAX_CONTINUATIONS:
        text = text.rstrip()  # le contenu assistant prefill ne peut finir par un blanc
        if not text:
            break
        continuations += 1
        logger.warning(
            "Réponse %s tronquée (max_tokens) — continuation %d/%d",
            agent_name,
            continuations,
            MAX_CONTINUATIONS,
        )
        cont_kwargs = {
            **kwargs,
            "messages": [*base_messages, {"role": "assistant", "content": text}],
        }
        response = await retry_transient_async(
            lambda: client.messages.create(**cont_kwargs), label=f"{agent_name}/anthropic"
        )
        text += _anthropic_text(response)

    if response.stop_reason == "max_tokens":
        logger.error(
            "Réponse %s toujours tronquée après %d continuations — texte best-effort renvoyé",
            agent_name,
            MAX_CONTINUATIONS,
        )
    return text


def _gemini_text(response: Any) -> str:
    text = getattr(response, "text", None) or ""
    if not text and getattr(response, "candidates", None):
        parts = response.candidates[0].content.parts  # type: ignore[union-attr]
        text = "".join(getattr(p, "text", "") or "" for p in parts)
    return text


def _gemini_truncated(response: Any) -> bool:
    candidates = getattr(response, "candidates", None)
    if not candidates:
        return False
    reason = getattr(candidates[0], "finish_reason", None)
    return getattr(reason, "name", str(reason)) == "MAX_TOKENS"


def _build_vertex_credentials(gcp: GcpCredentials) -> Any | None:
    """Credentials google-auth pour Vertex AI à partir d'un compte de service GCP."""
    from google.oauth2 import service_account

    scopes = ["https://www.googleapis.com/auth/cloud-platform"]
    if gcp.credentials_json:
        return service_account.Credentials.from_service_account_info(
            json.loads(gcp.credentials_json), scopes=scopes
        )
    if gcp.adc_path:
        return service_account.Credentials.from_service_account_file(
            gcp.adc_path, scopes=scopes
        )
    # Ni JSON ni fichier explicite : laisse genai utiliser l'ADC de l'environnement.
    return None


async def _call_gemini_text(
    *,
    api_key: str,
    model: str,
    prompt: str,
    system: str | None,
    max_tokens: int,
    cacheable_context: str | None,
    agent_name: str = "llm",
    use_vertex: bool = False,
    gcp: GcpCredentials | None = None,
) -> str:
    from google import genai
    from google.genai import types

    if use_vertex and gcp is not None:
        client = genai.Client(
            vertexai=True,
            project=gcp.project_id,
            location=gcp.location,
            credentials=_build_vertex_credentials(gcp),
        )
    else:
        client = genai.Client(api_key=api_key)
    full_prompt = prompt
    if cacheable_context and cacheable_context.strip():
        full_prompt = f"{cacheable_context.strip()}\n\n{prompt}"

    config_kwargs: dict[str, Any] = {"max_output_tokens": max_tokens}
    if system and system.strip():
        config_kwargs["system_instruction"] = system.strip()
    config = types.GenerateContentConfig(**config_kwargs)

    user_turn = types.Content(role="user", parts=[types.Part(text=full_prompt)])
    response = await retry_transient_async(
        lambda: client.aio.models.generate_content(
            model=model, contents=[user_turn], config=config
        ),
        label=f"{agent_name}/gemini",
    )
    text = _gemini_text(response)

    continuations = 0
    while _gemini_truncated(response) and continuations < MAX_CONTINUATIONS and text.strip():
        continuations += 1
        logger.warning(
            "Réponse %s tronquée (MAX_TOKENS) — continuation %d/%d",
            agent_name,
            continuations,
            MAX_CONTINUATIONS,
        )
        contents = [
            user_turn,
            types.Content(role="model", parts=[types.Part(text=text)]),
            types.Content(
                role="user",
                parts=[
                    types.Part(
                        text=(
                            "Continue exactement où tu t'es arrêté, sans rien répéter. "
                            "Ne renvoie que la suite brute (pas de markdown ni de commentaire)."
                        )
                    )
                ],
            ),
        ]
        response = await retry_transient_async(
            lambda: client.aio.models.generate_content(
                model=model, contents=contents, config=config
            ),
            label=f"{agent_name}/gemini",
        )
        text += _gemini_text(response)

    if _gemini_truncated(response):
        logger.error(
            "Réponse %s toujours tronquée après %d continuations — texte best-effort renvoyé",
            agent_name,
            MAX_CONTINUATIONS,
        )

    if not text.strip():
        raise RuntimeError(f"Réponse Gemini vide ({model})")
    return text.strip()


def preferences_to_json(prefs: dict[str, AgentLlmPreference]) -> dict:
    return {
        name: {"provider": p.provider, "model": p.model, "tier": p.tier}
        for name, p in prefs.items()
    }
