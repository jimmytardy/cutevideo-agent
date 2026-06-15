from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from agent.core.auth import create_oauth_state, decode_oauth_state
from agent.core.concurrency import can_start_pipeline, count_running_pipelines
from agent.core.database import Channel, Project, User, get_db
from agent.core.queue import queue
from agent.core.subscription import QuotaExceededError, check_can_create_channel
from agent.skills.publisher import composio_client
from api.authorization import get_user_channel
from api.deps import get_current_user
from api.models import (
    ChannelCreate,
    ChannelIntegrationsResponse,
    ChannelResponse,
    ChannelUpdate,
    ProjectResponse,
    TikTokConnectResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/channels", tags=["channels"])


def _channel_to_response(channel: Channel) -> ChannelResponse:
    return ChannelResponse.model_validate(channel)


@router.get("", response_model=list[ChannelResponse])
async def list_channels(
    active_only: bool = Query(default=False),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[Channel]:
    query = select(Channel).where(Channel.user_id == current_user.id).order_by(Channel.name)
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
        .where(Project.channel_id == channel_id, Channel.user_id == current_user.id)
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


@router.get("/{channel_id}/status")
async def get_channel_status(
    channel_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    channel = await get_user_channel(db, channel_id, current_user)
    running = await count_running_pipelines(channel_id)
    slot_free = await can_start_pipeline(channel_id)

    result = await db.execute(
        select(Project).where(Project.channel_id == channel_id, Project.status == "running")
    )
    running_projects = result.scalars().all()
    agent_statuses: dict[str, dict[str, str]] = {}
    for project in running_projects:
        agent_statuses[str(project.id)] = await queue.get_all_agent_statuses(str(project.id))

    return {
        "channel_id": str(channel_id),
        "slug": channel.slug,
        "running_pipelines": running,
        "max_concurrent_pipelines": channel.max_concurrent_pipelines,
        "slot_available": slot_free,
        "running_project_ids": [str(p.id) for p in running_projects],
        "agent_statuses": agent_statuses,
    }


@router.get("/{channel_id}/integrations", response_model=ChannelIntegrationsResponse)
async def get_channel_integrations(
    channel_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ChannelIntegrationsResponse:
    channel = await get_user_channel(db, channel_id, current_user)
    return ChannelIntegrationsResponse(
        tiktok_connected=composio_client.tiktok_is_connected(channel),
        tiktok_enabled=channel.tiktok_enabled,
        youtube_configured=bool(channel.youtube_channel_id),
        instagram_configured=bool(channel.instagram_page_id),
    )


@router.post("/{channel_id}/connect/tiktok", response_model=TikTokConnectResponse)
async def connect_tiktok(
    channel_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> TikTokConnectResponse:
    channel = await get_user_channel(db, channel_id, current_user)
    if not channel.tiktok_enabled:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="TikTok désactivé pour cette chaîne")

    try:
        oauth = await composio_client.initiate_tiktok_oauth(channel)
    except RuntimeError as e:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(e)) from e

    state = create_oauth_state(
        user_id=current_user.id,
        channel_id=channel_id,
        purpose="tiktok_connect",
        extra={"connection_id": oauth["connection_id"]},
    )
    return TikTokConnectResponse(
        redirect_url=oauth["redirect_url"],
        connection_id=oauth["connection_id"],
        state=state,
    )


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


@router.get("/{channel_id}/runway-status")
async def get_runway_status(
    channel_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    channel = await get_user_channel(db, channel_id, current_user)

    from agent.core.channel_config import resolve_channel_config
    from agent.core.runway_budget import get_monthly_runway_cost_usd, get_runway_credit_error
    from agent.core.subscription import resolve_user_limits

    limits = await resolve_user_limits(db, current_user)
    cfg = resolve_channel_config(channel, subscription_limits=limits)
    runway_cfg = cfg.runway
    spent = await get_monthly_runway_cost_usd(str(channel_id))
    credit_error = await get_runway_credit_error(str(channel_id))

    return {
        "enabled": runway_cfg.enabled,
        "monthly_budget_usd": runway_cfg.monthly_budget_usd,
        "spent_usd": round(spent, 2),
        "remaining_usd": round(max(0.0, runway_cfg.monthly_budget_usd - spent), 2),
        "credit_error": credit_error,
        "model": runway_cfg.model,
        "cost_per_clip_usd": round(runway_cfg.default_duration_s * runway_cfg.cost_per_second_usd, 2),
    }


async def _get_channel_or_404(db: AsyncSession, channel_id: uuid.UUID) -> Channel:
    """Compatibilité modules externes (cost, onboarding) — préférer get_user_channel."""
    result = await db.execute(select(Channel).where(Channel.id == channel_id))
    channel = result.scalar_one_or_none()
    if not channel:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chaîne introuvable")
    return channel
