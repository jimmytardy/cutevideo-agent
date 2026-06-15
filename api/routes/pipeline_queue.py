from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query

from agent.core.pipeline_queue import get_queue_snapshot
from agent.core.database import User
from api.deps import get_current_user
from api.models import PipelineQueueEntryResponse

router = APIRouter(prefix="/api/v1/pipeline-queue", tags=["pipeline-queue"])


@router.get("", response_model=list[PipelineQueueEntryResponse])
async def list_pipeline_queue(
    limit: int = Query(default=50, ge=1, le=200),
    current_user: User = Depends(get_current_user),
) -> list[PipelineQueueEntryResponse]:
    """Liste la file d'attente globale (projets de l'utilisateur courant)."""
    entries = await get_queue_snapshot(limit=limit, user_id=current_user.id)
    return [PipelineQueueEntryResponse.model_validate(entry) for entry in entries]
