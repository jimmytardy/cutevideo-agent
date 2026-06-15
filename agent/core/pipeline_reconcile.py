from __future__ import annotations

import logging
import uuid

from sqlalchemy import select

from agent.core.base_agent import stop_running_agent_runs
from agent.core.database import AsyncSessionFactory, Channel, Project
from agent.core.pipeline_lease import has_active_lease
from agent.core.pipeline_queue import PipelineAlreadyQueuedError, enqueue_pipeline_task, is_queued
from agent.core.queue import queue

logger = logging.getLogger(__name__)

_RECONCILE_REASON = "Worker interrompu — reprise automatique"


async def reconcile_orphan_running_projects(*, worker_id: str) -> int:
    """Remet en file les projets ``running`` sans lease Redis actif."""
    await queue.connect()

    async with AsyncSessionFactory() as session:
        result = await session.execute(select(Project).where(Project.status == "running"))
        projects = list(result.scalars().all())

    reconciled = 0
    for project in projects:
        if await has_active_lease(project.id):
            continue
        if await is_queued(project.id):
            continue

        await stop_running_agent_runs(project.id, reason=_RECONCILE_REASON)
        await queue.clear_agent_statuses(str(project.id))

        async with AsyncSessionFactory() as session:
            channel = await session.get(Channel, project.channel_id)
            user_id = channel.user_id if channel else None

        try:
            await enqueue_pipeline_task(
                project.id,
                user_id=user_id,
                reconcile_orphan=True,
            )
        except PipelineAlreadyQueuedError:
            logger.info(
                "Réconciliation ignorée projet=%s (déjà en file)",
                project.id,
            )
            continue
        except RuntimeError as exc:
            logger.warning(
                "Réconciliation échouée projet=%s : %s",
                project.id,
                exc,
            )
            continue

        reconciled += 1
        logger.info(
            "Réconciliation projet=%s remis en file (worker=%s)",
            project.id,
            worker_id,
        )

    if reconciled:
        logger.info(
            "Réconciliation terminée : %d projet(s) remis en file (worker=%s)",
            reconciled,
            worker_id,
        )
    return reconciled
