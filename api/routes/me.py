from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agent.core.api_keys import (
    ALLOWED_PROVIDERS,
    api_key_hint_from_encrypted,
    encrypt_api_key,
    get_user_api_key_row,
)
from agent.core.database import User, UserApiKey, get_db
from agent.core.agent_llm_constraints import normalize_agent_preference, normalize_preferences_map
from agent.core.agent_llm_recommendations import all_agent_llm_recommendations
from agent.core.llm_resolver import (
    CONFIGURABLE_AGENTS,
    LLM_PREFERENCE_ALIAS,
    AgentLlmPreference,
    preferences_to_json,
    parse_agent_preferences,
)
from agent.core.subscription import (
    QuotaExceededError,
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
    agents = sorted(CONFIGURABLE_AGENTS)
    display_agents = sorted(set(agents) | set(LLM_PREFERENCE_ALIAS.keys()))
    normalized_by_agent = {
        agent: normalize_agent_preference(agent, prefs.get(agent, AgentLlmPreference()))
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
    )


@router.put("/agent-llm", response_model=AgentLlmConfigResponse)
async def update_agent_llm_config(
    body: AgentLlmUpdateRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AgentLlmConfigResponse:
    has_gemini = await get_user_api_key_row(db, user.id, "gemini") is not None
    if not has_gemini and body.preferences:
        raise HTTPException(
            status_code=400,
            detail="Configurez d'abord une clé Gemini pour personnaliser les modèles par agent.",
        )
    parsed = {
        name: normalize_agent_preference(
            name,
            parse_agent_preferences({name: pref.model_dump()})[name],
        )
        for name, pref in body.preferences.items()
        if name in CONFIGURABLE_AGENTS
    }
    user.agent_llm_preferences = preferences_to_json(parsed)
    await db.commit()
    await db.refresh(user)
    return await get_agent_llm_config(user=user, db=db)
