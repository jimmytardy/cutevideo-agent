from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from agent.core.auth import create_oauth_state, decode_oauth_state
from agent.core.database import Channel, Project, User, get_db
from agent.core.subscription import QuotaExceededError, check_can_create_channel
from agent.core.config import settings
from agent.skills.publisher import tiktok_providers
from agent.skills.publisher.tiktok_providers import get_tiktok_publisher, provider_account, provider_name
from api.authorization import channel_owner_clause, get_user_channel
from api.deps import get_current_user
from api.models import (
    ChannelCreate,
    ChannelIntegrationsResponse,
    ChannelResponse,
    ChannelUpdate,
    ProjectResponse,
    TikTokConnectResponse,
    TikTokFinishRequest,
    TikTokProviderUpdate,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/channels", tags=["channels"])


@router.get("", response_model=list[ChannelResponse])
async def list_channels(
    active_only: bool = Query(default=False),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[Channel]:
    query = select(Channel).where(channel_owner_clause(current_user)).order_by(Channel.name)
    if active_only:
        query = query.where(Channel.is_active.is_(True))
    result = await db.execute(query)
    return list(result.scalars().all())


@router.post("", response_model=ChannelResponse, status_code=status.HTTP_201_CREATED)
async def create_channel(
    body: ChannelCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Channel:
    try:
        await check_can_create_channel(db, current_user)
    except QuotaExceededError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc

    existing = await db.execute(
        select(Channel).where(Channel.user_id == current_user.id, Channel.slug == body.slug)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Slug déjà utilisé")

    channel = Channel(
        user_id=current_user.id,
        slug=body.slug,
        name=body.name,
        theme_category=body.theme_category,
        niche_prompt=body.niche_prompt,
        config=body.config,
        youtube_channel_id=body.youtube_channel_id,
        youtube_channel_url=body.youtube_channel_url,
        instagram_page_id=body.instagram_page_id,
        tiktok_enabled=body.tiktok_enabled,
        composio_user_id=body.slug,
        max_concurrent_pipelines=body.max_concurrent_pipelines,
    )
    db.add(channel)
    await db.commit()
    await db.refresh(channel)
    return channel


@router.get("/{channel_id}", response_model=ChannelResponse)
async def get_channel(
    channel_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Channel:
    return await get_user_channel(db, channel_id, current_user)


@router.patch("/{channel_id}", response_model=ChannelResponse)
async def update_channel(
    channel_id: uuid.UUID,
    body: ChannelUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Channel:
    channel = await get_user_channel(db, channel_id, current_user)
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(channel, field, value)
    await db.commit()
    await db.refresh(channel)
    return channel


@router.delete("/{channel_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_channel(
    channel_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    channel = await get_user_channel(db, channel_id, current_user)
    projects = await db.execute(
        select(func.count()).select_from(Project).where(Project.channel_id == channel.id)
    )
    if projects.scalar_one() > 0:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Impossible de supprimer une chaîne avec des projets associés",
        )
    await db.delete(channel)
    await db.commit()


@router.get("/{channel_id}/projects", response_model=list[ProjectResponse])
async def list_channel_projects(
    channel_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[ProjectResponse]:
    await get_user_channel(db, channel_id, current_user)
    result = await db.execute(
        select(Project, Channel.name)
        .join(Channel, Channel.id == Project.channel_id)
        .where(Project.channel_id == channel_id, channel_owner_clause(current_user))
        .order_by(Project.created_at.desc())
    )
    return [
        ProjectResponse(
            id=p.id,
            channel_id=p.channel_id,
            channel_name=name,
            theme=p.theme,
            title=p.title,
            target_duration_seconds=p.target_duration_seconds,
            status=p.status,
            config=p.config,
            created_at=p.created_at,
            updated_at=p.updated_at,
        )
        for p, name in result.all()
    ]


def _integrations(channel: Channel) -> ChannelIntegrationsResponse:
    provider = provider_name(channel)
    return ChannelIntegrationsResponse(
        tiktok_connected=get_tiktok_publisher(channel).is_connected(channel),
        tiktok_enabled=channel.tiktok_enabled,
        tiktok_provider=provider,
        tiktok_username=provider_account(channel, provider).get("username"),
        youtube_configured=bool(channel.youtube_channel_id),
        instagram_configured=bool(channel.instagram_page_id),
    )


@router.get("/{channel_id}/integrations", response_model=ChannelIntegrationsResponse)
async def get_channel_integrations(
    channel_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ChannelIntegrationsResponse:
    channel = await get_user_channel(db, channel_id, current_user)
    return _integrations(channel)


@router.put("/{channel_id}/tiktok-provider", response_model=ChannelIntegrationsResponse)
async def set_tiktok_provider(
    channel_id: uuid.UUID,
    body: TikTokProviderUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ChannelIntegrationsResponse:
    """Choisit le fournisseur de publication TikTok de la chaîne (Composio, Post for Me, Zernio)."""
    channel = await get_user_channel(db, channel_id, current_user)
    config = dict(channel.config or {})
    config["tiktok"] = {**tiktok_providers.tiktok_settings(channel), "provider": body.provider}
    channel.config = config
    await db.commit()
    await db.refresh(channel)
    return _integrations(channel)


@router.post("/{channel_id}/connect/tiktok", response_model=TikTokConnectResponse)
async def connect_tiktok(
    channel_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> TikTokConnectResponse:
    channel = await get_user_channel(db, channel_id, current_user)
    if not channel.tiktok_enabled:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="TikTok désactivé pour cette chaîne")

    provider = provider_name(channel)
    state = create_oauth_state(
        user_id=current_user.id,
        channel_id=channel_id,
        purpose="tiktok_connect",
        extra={"provider": provider},
    )
    # Retour sur une page du dashboard : la redirection navigateur ne porte pas le jeton,
    # c'est la page qui finalise via POST /connect/tiktok/finish.
    redirect_url = f"{settings.api_base_url.rstrip('/')}/channels/{channel_id}/tiktok-connected?state={state}"
    try:
        oauth = await get_tiktok_publisher(channel).start_connect(channel, redirect_url)
    except Exception as e:
        logger.warning("Connexion TikTok (%s) impossible pour %s : %s", provider, channel.slug, e)
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(e)) from e

    extra = oauth.get("extra") or {}
    if extra.get("profile_id"):
        channel.config = tiktok_providers.with_provider_account(
            channel, provider, {"profile_id": extra["profile_id"]}
        )
        await db.commit()
    if provider == "composio":
        # Flux historique : le callback GET attend le state « composio » avec le connection_id.
        state = create_oauth_state(
            user_id=current_user.id,
            channel_id=channel_id,
            purpose="tiktok_connect",
            extra={"provider": provider, "connection_id": extra.get("connection_id")},
        )
    return TikTokConnectResponse(
        redirect_url=oauth["redirect_url"],
        connection_id=str(extra.get("connection_id") or ""),
        state=state,
    )


@router.post("/{channel_id}/connect/tiktok/finish", response_model=ChannelIntegrationsResponse)
async def finish_tiktok_connect(
    channel_id: uuid.UUID,
    body: TikTokFinishRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ChannelIntegrationsResponse:
    try:
        payload = decode_oauth_state(body.state, expected_purpose="tiktok_connect")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if payload.get("channel_id") != str(channel_id):
        raise HTTPException(status_code=400, detail="State channel_id invalide")

    channel = await get_user_channel(db, channel_id, current_user)
    extra = payload.get("extra") or {}
    provider = str(extra.get("provider") or provider_name(channel))
    publisher = tiktok_providers._PUBLISHERS.get(provider)
    if publisher is None:
        raise HTTPException(status_code=400, detail=f"Fournisseur TikTok inconnu : {provider}")
    try:
        account = await publisher.finish_connect(
            channel, body.params, {**provider_account(channel, provider), **extra}
        )
    except Exception as e:
        logger.error("Finalisation TikTok (%s) échouée pour %s : %s", provider, channel.slug, e)
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(e)) from e

    if provider == "composio":
        channel.composio_tiktok_account_id = account["account_id"]
    channel.config = tiktok_providers.with_provider_account(channel, provider, account)
    await db.commit()
    await db.refresh(channel)
    return _integrations(channel)


@router.get("/{channel_id}/connect/tiktok/callback")
async def tiktok_oauth_callback(
    channel_id: uuid.UUID,
    connection_id: str = Query(...),
    state: str = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, str]:
    try:
        payload = decode_oauth_state(state, expected_purpose="tiktok_connect")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if payload.get("channel_id") != str(channel_id):
        raise HTTPException(status_code=400, detail="State channel_id invalide")

    channel = await get_user_channel(db, channel_id, current_user)

    try:
        from agent.skills.publisher import composio_client

        account_id = await composio_client.wait_for_tiktok_connection(connection_id, channel)
    except Exception as e:
        logger.error("Callback TikTok échoué pour %s : %s", channel.slug, e)
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(e)) from e

    await db.execute(
        update(Channel)
        .where(Channel.id == channel.id)
        .values(composio_tiktok_account_id=account_id)
    )
    await db.commit()

    return {
        "status": "connected",
        "channel_slug": channel.slug,
        "composio_tiktok_account_id": account_id,
    }
