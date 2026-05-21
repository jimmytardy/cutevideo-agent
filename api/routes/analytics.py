from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agent.core.database import Analytics, Publication, get_db
from api.models import AnalyticsResponse, PublicationResponse

router = APIRouter(prefix="/api/v1/analytics", tags=["analytics"])


@router.get("/publications/{project_id}", response_model=list[PublicationResponse])
async def list_publications(
    project_id: uuid.UUID, db: AsyncSession = Depends(get_db)
) -> list[Publication]:
    from agent.core.database import Video
    result = await db.execute(
        select(Publication)
        .join(Video, Publication.video_id == Video.id)
        .where(Video.project_id == project_id)
        .order_by(Publication.published_at.desc())
    )
    return list(result.scalars().all())


@router.get("/stats/{publication_id}", response_model=list[AnalyticsResponse])
async def get_analytics(
    publication_id: uuid.UUID, db: AsyncSession = Depends(get_db)
) -> list[Analytics]:
    result = await db.execute(
        select(Analytics)
        .where(Analytics.publication_id == publication_id)
        .order_by(Analytics.fetched_at.desc())
    )
    return list(result.scalars().all())
