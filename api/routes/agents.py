from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agent.core.database import AgentRun, User, get_db
from api.authorization import get_user_project
from api.deps import get_current_user
from api.models import AgentRunResponse

router = APIRouter(prefix="/api/v1/agents", tags=["agents"])


@router.get("/runs/{project_id}", response_model=list[AgentRunResponse])
async def list_agent_runs(
    project_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[AgentRun]:
    await get_user_project(db, project_id, current_user)
    result = await db.execute(
        select(AgentRun)
        .where(AgentRun.project_id == project_id)
        .order_by(AgentRun.started_at.desc())
    )
    return list(result.scalars().all())
