from __future__ import annotations

import logging
import uuid
from typing import Any

from agent.core.queue import PIPELINE_QUEUE, queue

logger = logging.getLogger(__name__)


async def enqueue_pipeline(
    project_id: uuid.UUID,
    *,
    start_from: str | None = None,
    critic_feedback: list[dict[str, Any]] | None = None,
    critic_start_from: str | None = None,
    resume_iteration: int | None = None,
) -> None:
    """Enqueue un pipeline pour exécution par le worker Redis."""
    await queue.clear_pipeline_cancel(str(project_id))
    payload: dict[str, Any] = {
        "project_id": str(project_id),
        "start_from": start_from,
        "critic_feedback": critic_feedback,
        "critic_start_from": critic_start_from,
        "resume_iteration": resume_iteration,
    }
    await queue.push_task(PIPELINE_QUEUE, payload)
    logger.info("Pipeline enqueued pour le projet %s", project_id)


async def request_pipeline_cancel(project_id: uuid.UUID) -> None:
    """Demande l'arrêt coopératif d'un pipeline en cours dans le worker."""
    await queue.request_pipeline_cancel(str(project_id))
