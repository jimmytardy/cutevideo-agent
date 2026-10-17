from __future__ import annotations


from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agent.core.api_keys import (
    ADMIN_ONLY_PROVIDERS,
    ALLOWED_PROVIDERS,
    api_key_hint_from_encrypted,
    decrypt_api_key,
    encrypt_api_key,
    get_user_api_key_row,
)
from agent.core.api_key_validation import ApiKeyValidationError, KeyHealth, check_api_key, validate_api_key
from agent.core.claude_cli_llm import claude_cli_available
from agent.core.concurrency import bounded_gather
from agent.core.database import User, UserApiKey, get_db
from agent.core.agent_llm_constraints import normalize_preference, normalize_preferences_map
from agent.core.agent_llm_recommendations import all_agent_llm_recommendations
from agent.core.llm_resolver import (
    CONFIGURABLE_AGENTS,
    LLM_PREFERENCE_ALIAS,
    AgentLlmPreference,
    preferences_to_json,
    parse_agent_preferences,
)
from agent.core.subscription import (
    count_user_channels,
    get_plan_for_user,
    is_unlimited,
    resolve_user_limits,
    sum_user_storage_bytes,
)
from api.deps import get_current_user

router = APIRouter(prefix="/api/v1/me", tags=["me"])


class SubscriptionResponse(BaseModel):
    plan_slug: str
    plan_name: str
    is_unlimited: bool
    limits: dict
    usage: dict


class ApiKeyStatus(BaseModel):
    provider: str
    configured: bool
    key_hint: str | None = None
    metadata: dict | None = None


class ApiKeyHealth(BaseModel):
    provider: str
    # ok | invalid | expired | no_credit | quota | unavailable (agent/core/api_key_validation.py)
    status: str
    detail: str = ""


class ApiKeyUpsert(BaseModel):
    api_key: str = Field(min_length=1)
    metadata: dict | None = None


class AgentLlmPreferenceModel(BaseModel):
    provider: str = "gemini"
    model: str = "gemini-2.5-flash-lite"
    tier: str = "free"


class AgentLlmConfigResponse(BaseModel):
    agents: list[str]
    linked_agents: dict[str, str]
    preferences: dict[str, AgentLlmPreferenceModel]
    recommendations: dict[str, str]
    has_gemini_key: bool
    has_anthropic_key: bool
    # Abonnement Claude via le CLI : admins ayant enregistré leur token `claude setup-token`.
    has_claude_cli: bool = False


class AgentLlmUpdateRequest(BaseModel):
    preferences: dict[str, AgentLlmPreferenceModel]


@router.get("/subscription", response_model=SubscriptionResponse)
async def get_my_subscription(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SubscriptionResponse:
    plan = await get_plan_for_user(db, user)
    limits = await resolve_user_limits(db, user)
    channels = await count_user_channels(db, user.id)
    storage = await sum_user_storage_bytes(db, user.id)
    return SubscriptionResponse(
        plan_slug=plan.slug,
        plan_name=plan.name,
        is_unlimited=is_unlimited(plan),
        limits=limits.model_dump(),
        usage={
            "channels": channels,
            "storage_bytes": storage,
        },
    )


@router.get("/api-keys", response_model=list[ApiKeyStatus])
async def list_my_api_keys(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[ApiKeyStatus]:
    result = await db.execute(
        select(UserApiKey).where(UserApiKey.user_id == user.id, UserApiKey.is_active.is_(True))
    )
    configured = {row.provider: row for row in result.scalars().all()}
    return [
        ApiKeyStatus(
            provider=provider,
            configured=provider in configured,
            key_hint=(
                api_key_hint_from_encrypted(configured[provider].encrypted_key)
                if provider in configured
                else None
            ),
            metadata=configured[provider].metadata_ if provider in configured else None,
        )
        for provider in sorted(ALLOWED_PROVIDERS)
        if user.is_admin or provider not in ADMIN_ONLY_PROVIDERS
    ]


@router.get("/api-keys/health", response_model=list[ApiKeyHealth])
async def check_my_api_keys(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[ApiKeyHealth]:
    """Teste chaque clé enregistrée auprès de son fournisseur (expirée, crédit épuisé, quota…)."""
    result = await db.execute(
        select(UserApiKey).where(UserApiKey.user_id == user.id, UserApiKey.is_active.is_(True))
    )
    rows = sorted(result.scalars().all(), key=lambda r: r.provider)

    async def _check(row: UserApiKey) -> KeyHealth:
        try:
            key = decrypt_api_key(row.encrypted_key)
        except ValueError:
            return KeyHealth("invalid", "Clé illisible (clé de chiffrement modifiée) : ressaisissez-la.")
        return await check_api_key(row.provider, key, row.metadata_)

    healths = await bounded_gather(*(_check(row) for row in rows))
    return [
        ApiKeyHealth(provider=row.provider, status=health.status, detail=health.detail)
        for row, health in zip(rows, healths, strict=True)
    ]


@router.put("/api-keys/{provider}", response_model=ApiKeyStatus)
async def upsert_my_api_key(
    provider: str,
    body: ApiKeyUpsert,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ApiKeyStatus:
    if provider not in ALLOWED_PROVIDERS:
        raise HTTPException(status_code=400, detail="Provider non supporté")
    if provider in ADMIN_ONLY_PROVIDERS and not user.is_admin:
        raise HTTPException(status_code=403, detail="Réservé aux administrateurs")
    try:
        await validate_api_key(provider, body.api_key, body.metadata)
    except ApiKeyValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    row = await get_user_api_key_row(db, user.id, provider)
    encrypted = encrypt_api_key(body.api_key.strip())
    if row:
        row.encrypted_key = encrypted
        row.metadata_ = body.metadata
        row.is_active = True
    else:
        db.add(
            UserApiKey(
                user_id=user.id,
                provider=provider,
                encrypted_key=encrypted,
                metadata_=body.metadata,
            )
        )
    await db.commit()
    return ApiKeyStatus(
        provider=provider,
        configured=True,
        key_hint=api_key_hint_from_encrypted(encrypted),
        metadata=body.metadata,
    )


@router.delete("/api-keys/{provider}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_my_api_key(
    provider: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    row = await get_user_api_key_row(db, user.id, provider)
    if row:
        await db.delete(row)
        await db.commit()


@router.get("/agent-llm", response_model=AgentLlmConfigResponse)
async def get_agent_llm_config(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AgentLlmConfigResponse:
    prefs = normalize_preferences_map(parse_agent_preferences(user.agent_llm_preferences))
    has_gemini = await get_user_api_key_row(db, user.id, "gemini") is not None
    has_anthropic = await get_user_api_key_row(db, user.id, "anthropic") is not None
    has_subscription = bool(user.is_admin) and (
        await get_user_api_key_row(db, user.id, "claude_subscription") is not None
    )
    agents = sorted(CONFIGURABLE_AGENTS)
    display_agents = sorted(set(agents) | set(LLM_PREFERENCE_ALIAS.keys()))
    normalized_by_agent = {
        agent: normalize_preference(prefs.get(agent, AgentLlmPreference()))
        for agent in agents
    }
    return AgentLlmConfigResponse(
        agents=agents,
        linked_agents=dict(LLM_PREFERENCE_ALIAS),
        preferences={
            k: AgentLlmPreferenceModel(provider=v.provider, model=v.model, tier=v.tier)
            for k, v in normalized_by_agent.items()
        },
        recommendations=all_agent_llm_recommendations(display_agents),
        has_gemini_key=has_gemini,
        has_anthropic_key=has_anthropic,
        has_claude_cli=has_subscription and claude_cli_available(),
    )


@router.put("/agent-llm", response_model=AgentLlmConfigResponse)
async def update_agent_llm_config(
    body: AgentLlmUpdateRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AgentLlmConfigResponse:
    # Chaque fournisseur choisi doit avoir la clé de l'utilisateur (aucune clé plateforme).
    required = {
        "gemini": ("gemini", "une clé Gemini"),
        "anthropic": ("anthropic", "une clé Anthropic"),
        "claude_cli": ("claude_subscription", "le token d'abonnement Claude (admins)"),
    }
    for choice in sorted({pref.provider for pref in body.preferences.values()} & set(required)):
        key_provider, label = required[choice]
        allowed = user.is_admin or key_provider not in ADMIN_ONLY_PROVIDERS
        if not allowed or await get_user_api_key_row(db, user.id, key_provider) is None:
            raise HTTPException(
                status_code=400,
                detail=f"Ajoutez d'abord {label} dans Compte → Clés API.",
            )
    parsed = {
        name: normalize_preference(parse_agent_preferences({name: pref.model_dump()})[name])
        for name, pref in body.preferences.items()
        if name in CONFIGURABLE_AGENTS
    }
    user.agent_llm_preferences = preferences_to_json(parsed)
    await db.commit()
    await db.refresh(user)
    return await get_agent_llm_config(user=user, db=db)
