from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agent.core.database import MediaAsset, get_db
from api.models import MediaAssetResponse

router = APIRouter(prefix="/api/v1/media", tags=["media"])


@router.get("/{project_id}", response_model=list[MediaAssetResponse])
async def list_media(
    project_id: uuid.UUID,
    segment_order: int | None = Query(None),
    selected_only: bool = Query(False),
    db: AsyncSession = Depends(get_db),
) -> list[MediaAsset]:
    query = select(MediaAsset).where(MediaAsset.project_id == project_id)
    if segment_order is not None:
        query = query.where(MediaAsset.segment_order == segment_order)
    if selected_only:
        query = query.where(MediaAsset.selected == True)
    query = query.order_by(MediaAsset.segment_order, MediaAsset.created_at)

    result = await db.execute(query)
    return list(result.scalars().all())
