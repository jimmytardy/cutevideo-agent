from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agent.agents.distribution_agent import DistributionAgent
from agent.core.database import Publication, get_db
from api.models import PublicationResponse

router = APIRouter(prefix="/api/v1/distribution", tags=["distribution"])


@router.post("/run", status_code=status.HTTP_202_ACCEPTED)
async def run_distribution() -> dict:
    """Déclenche planification + publication des créneaux dus."""
    return await DistributionAgent().run_scheduled()


@router.get("/queue", response_model=list[PublicationResponse])
async def list_distribution_queue(
    channel_id: uuid.UUID | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
) -> list[Publication]:
    query = (
        select(Publication)
        .where(Publication.status.in_(("scheduled", "failed", "publishing")))
        .order_by(Publication.scheduled_at.asc().nulls_last())
    )
    if channel_id:
        query = query.where(Publication.channel_id == channel_id)

    result = await db.execute(query)
    return list(result.scalars().all())


@router.get("/publications/{publication_id}", response_model=PublicationResponse)
async def get_scheduled_publication(
    publication_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> Publication:
    result = await db.execute(
        select(Publication).where(Publication.id == publication_id)
    )
    pub = result.scalar_one_or_none()
    if not pub:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Publication introuvable")
    return pub
