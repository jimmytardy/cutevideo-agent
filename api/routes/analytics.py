from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agent.core.database import Analytics, Channel, Publication, User, Video, get_db
from api.authorization import channel_owner_clause, get_user_project
from api.deps import get_current_user
from api.models import AnalyticsResponse, PublicationResponse

router = APIRouter(prefix="/api/v1/analytics", tags=["analytics"])


@router.get("/publications/{project_id}", response_model=list[PublicationResponse])
async def list_publications(
    project_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[Publication]:
    await get_user_project(db, project_id, current_user)
    result = await db.execute(
        select(Publication)
        .join(Video, Publication.video_id == Video.id)
        .where(Video.project_id == project_id)
        .order_by(Publication.published_at.desc())
    )
    return list(result.scalars().all())


@router.get("/stats/{publication_id}", response_model=list[AnalyticsResponse])
async def get_analytics(
    publication_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[Analytics]:
    result = await db.execute(
        select(Analytics)
        .join(Publication, Publication.id == Analytics.publication_id)
        .join(Channel, Channel.id == Publication.channel_id)
        .where(Analytics.publication_id == publication_id, channel_owner_clause(current_user))
        .order_by(Analytics.fetched_at.desc())
    )
    return list(result.scalars().all())
