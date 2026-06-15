from __future__ import annotations

import logging
import uuid
from typing import Any

from agent.core.pipeline_queue import (
    PipelineAlreadyQueuedError,
    QueueStatus,
    enqueue_pipeline_task,
    remove_from_queue,
)
from agent.core.queue import queue

logger = logging.getLogger(__name__)


async def enqueue_pipeline(
    project_id: uuid.UUID,
    *,
    user_id: uuid.UUID | None = None,
    start_from: str | None = None,
    critic_feedback: list[dict[str, Any]] | None = None,
    critic_start_from: str | None = None,
    resume_iteration: int | None = None,
) -> QueueStatus:
    """Enqueue un pipeline dans la file prioritaire Redis."""
    return await enqueue_pipeline_task(
        project_id,
        user_id=user_id,
        start_from=start_from,
        critic_feedback=critic_feedback,
        critic_start_from=critic_start_from,
        resume_iteration=resume_iteration,
    )


async def dequeue_pipeline(project_id: uuid.UUID) -> bool:
    """Retire un pipeline de la file d'attente."""
    return await remove_from_queue(project_id)


async def request_pipeline_cancel(project_id: uuid.UUID) -> None:
    """Demande l'arrêt coopératif d'un pipeline en cours dans le worker."""
    await queue.request_pipeline_cancel(str(project_id))
