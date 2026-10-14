from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agent.core.database import Publication, User, Video, get_db
from api.authorization import get_user_project
from api.deps import get_current_user
from api.models import PublicationResponse

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
