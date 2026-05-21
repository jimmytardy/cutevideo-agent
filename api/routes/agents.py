from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import AsyncGenerator

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agent.core.database import AgentRun, get_db
from agent.core.queue import queue
from api.models import AgentRunResponse

router = APIRouter(prefix="/api/v1/agents", tags=["agents"])


@router.get("/runs/{project_id}", response_model=list[AgentRunResponse])
async def list_agent_runs(
    project_id: uuid.UUID, db: AsyncSession = Depends(get_db)
) -> list[AgentRun]:
    result = await db.execute(
        select(AgentRun)
        .where(AgentRun.project_id == project_id)
        .order_by(AgentRun.started_at.desc())
    )
    return list(result.scalars().all())


@router.get("/status/{project_id}")
async def get_agent_statuses(project_id: uuid.UUID) -> dict[str, str]:
    """Retourne les statuts Redis de tous les agents d'un projet."""
    return await queue.get_all_agent_statuses(str(project_id))


@router.get("/stream/{project_id}")
async def stream_agent_statuses(project_id: uuid.UUID) -> StreamingResponse:
    """Server-Sent Events pour le monitoring temps réel des agents."""

    async def event_generator() -> AsyncGenerator[str, None]:
        while True:
            statuses = await queue.get_all_agent_statuses(str(project_id))
            data = json.dumps(statuses)
            yield f"data: {data}\n\n"
            await asyncio.sleep(1)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
