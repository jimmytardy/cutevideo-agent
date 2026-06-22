from __future__ import annotations

import uuid
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from agent.agents.content_planner_agent import ContentPlannerAgent
from agent.core.content_plan_models import DailyContentPlan
from agent.core.database import User, get_db
from api.authorization import get_user_channel
from api.deps import get_current_user

router = APIRouter(prefix="/api/v1/content-planning", tags=["content-planning"])


class ContentPlanRunResponse(BaseModel):
    production_date: str
    target_publish_date: str
    projects_created: int
    channels_skipped: int
    errors: int


class ChannelPlanResponse(BaseModel):
    plan: DailyContentPlan


@router.post("/run", response_model=ContentPlanRunResponse, status_code=status.HTTP_202_ACCEPTED)
async def run_content_planning_all() -> ContentPlanRunResponse:
    """Planifie les sujets du jour pour toutes les chaînes actives."""
    result = await ContentPlannerAgent().run_scheduled()
    return ContentPlanRunResponse(**result)


@router.post("/channels/{channel_id}/plan", response_model=ChannelPlanResponse)
async def plan_channel(
    channel_id: uuid.UUID,
    force: bool = Query(default=False, description="Recréer un plan même si déjà planifié aujourd'hui"),
    plan_date: date | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ChannelPlanResponse:
    await get_user_channel(db, channel_id, current_user)
    try:
        plan = await ContentPlannerAgent().run_for_channel(channel_id, plan_date=plan_date, force=force)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e)) from e
    if not plan:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Plan non généré")
    return ChannelPlanResponse(plan=plan)
