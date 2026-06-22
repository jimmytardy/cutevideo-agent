from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agent.core.database import MarketAnalysis, User, get_db
from api.deps import get_current_user
from api.models import MarketAnalysisDetailResponse, MarketAnalysisListItem

router = APIRouter(prefix="/api/v1/markets", tags=["markets"])


@router.get("", response_model=list[MarketAnalysisListItem])
async def list_market_analyses(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[MarketAnalysis]:
    query = select(MarketAnalysis).order_by(MarketAnalysis.created_at.desc())
    if not current_user.is_admin:
        query = query.where(MarketAnalysis.user_id == current_user.id)
    result = await db.execute(query)
    return list(result.scalars().all())


@router.get("/{analysis_id}", response_model=MarketAnalysisDetailResponse)
async def get_market_analysis(
    analysis_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> MarketAnalysis:
    query = select(MarketAnalysis).where(MarketAnalysis.id == analysis_id)
    if not current_user.is_admin:
        query = query.where(MarketAnalysis.user_id == current_user.id)
    result = await db.execute(query)
    analysis = result.scalar_one_or_none()
    if not analysis:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Analyse introuvable")
    return analysis
