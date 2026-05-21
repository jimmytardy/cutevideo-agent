from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from agent.core.concurrency import can_start_pipeline, count_running_pipelines
from agent.core.database import Channel, Project, get_db
from agent.core.queue import queue
from agent.skills.publisher import composio_client
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

_pending_tiktok_connections: dict[str, str] = {}


def _channel_to_response(channel: Channel) -> ChannelResponse:
    return ChannelResponse.model_validate(channel)


@router.get("/", response_model=list[ChannelResponse])
async def list_channels(
    active_only: bool = Query(default=False),
    db: AsyncSession = Depends(get_db),
) -> list[Channel]:
    query = select(Channel).order_by(Channel.name)
    if active_only:
        query = query.where(Channel.is_active.is_(True))
    result = await db.execute(query)
    return list(result.scalars().all())


@router.post("/", response_model=ChannelResponse, status_code=status.HTTP_201_CREATED)
async def create_channel(
    body: ChannelCreate, db: AsyncSession = Depends(get_db)
) -> Channel:
    existing = await db.execute(select(Channel).where(Channel.slug == body.slug))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Slug déjà utilisé")

    channel = Channel(
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
async def get_channel(channel_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> Channel:
    channel = await _get_channel_or_404(db, channel_id)
    return channel


@router.patch("/{channel_id}", response_model=ChannelResponse)
async def update_channel(
    channel_id: uuid.UUID, body: ChannelUpdate, db: AsyncSession = Depends(get_db)
) -> Channel:
    channel = await _get_channel_or_404(db, channel_id)
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(channel, field, value)
    await db.commit()
    await db.refresh(channel)
    return channel


@router.delete("/{channel_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_channel(channel_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> None:
    channel = await _get_channel_or_404(db, channel_id)
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
    channel_id: uuid.UUID, db: AsyncSession = Depends(get_db)
) -> list[ProjectResponse]:
    await _get_channel_or_404(db, channel_id)
    result = await db.execute(
        select(Project, Channel.name)
        .join(Channel, Channel.id == Project.channel_id)
        .where(Project.channel_id == channel_id)
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
async def get_channel_status(channel_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> dict:
    channel = await _get_channel_or_404(db, channel_id)
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
    channel_id: uuid.UUID, db: AsyncSession = Depends(get_db)
) -> ChannelIntegrationsResponse:
    channel = await _get_channel_or_404(db, channel_id)
    return ChannelIntegrationsResponse(
        tiktok_connected=composio_client.tiktok_is_connected(channel),
        tiktok_enabled=channel.tiktok_enabled,
        youtube_configured=bool(channel.youtube_channel_id),
        instagram_configured=bool(channel.instagram_page_id),
    )


@router.post("/{channel_id}/connect/tiktok", response_model=TikTokConnectResponse)
async def connect_tiktok(channel_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> TikTokConnectResponse:
    channel = await _get_channel_or_404(db, channel_id)
    if not channel.tiktok_enabled:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="TikTok désactivé pour cette chaîne")

    try:
        oauth = await composio_client.initiate_tiktok_oauth(channel)
    except RuntimeError as e:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(e)) from e

    _pending_tiktok_connections[oauth["connection_id"]] = str(channel_id)
    return TikTokConnectResponse(
        redirect_url=oauth["redirect_url"],
        connection_id=oauth["connection_id"],
    )


@router.get("/{channel_id}/connect/tiktok/callback")
async def tiktok_oauth_callback(
    connection_id: str = Query(...),
    channel_id: uuid.UUID | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    resolved_channel_id = channel_id
    if not resolved_channel_id and connection_id in _pending_tiktok_connections:
        resolved_channel_id = uuid.UUID(_pending_tiktok_connections[connection_id])

    if not resolved_channel_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="channel_id manquant")

    channel = await _get_channel_or_404(db, resolved_channel_id)

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
    _pending_tiktok_connections.pop(connection_id, None)

    return {
        "status": "connected",
        "channel_slug": channel.slug,
        "composio_tiktok_account_id": account_id,
    }


async def _get_channel_or_404(db: AsyncSession, channel_id: uuid.UUID) -> Channel:
    result = await db.execute(select(Channel).where(Channel.id == channel_id))
    channel = result.scalar_one_or_none()
    if not channel:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chaîne introuvable")
    return channel
