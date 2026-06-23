from __future__ import annotations

import asyncio
import os
import uuid
from collections.abc import Awaitable
from typing import TypeVar

from sqlalchemy import func, select, update

from agent.core.database import AsyncSessionFactory, Channel, Project

_T = TypeVar("_T")


def fanout_concurrency() -> int:
    """Nb max de tâches simultanées dans un fan-out de pipeline.

    Borne les `gather` par segment (narrateur, média) pour éviter qu'une vidéo
    à N segments lance N tâches d'un coup (N TTS/ffmpeg/téléchargements en
    parallèle → pic CPU/RAM). Réglable via PIPELINE_FANOUT_CONCURRENCY.
    """
    try:
        return max(1, int(os.getenv("PIPELINE_FANOUT_CONCURRENCY", "3")))
    except ValueError:
        return 3


def beat_fanout_concurrency() -> int:
    """Nb max de visual_beats traités en parallèle dans un segment (media_agent).

    Les étapes stock / scoring Gemini sont surtout I/O — on peut dépasser le
    fan-out segments. Réglable via MEDIA_BEAT_FANOUT_CONCURRENCY.
    """
    raw = os.getenv("MEDIA_BEAT_FANOUT_CONCURRENCY")
    if raw:
        try:
            return max(1, int(raw))
        except ValueError:
            pass
    return max(fanout_concurrency() * 2, 6)


async def bounded_gather(
    *awaitables: Awaitable[_T],
    limit: int | None = None,
    return_exceptions: bool = False,
) -> list[_T]:
    """Comme `asyncio.gather` mais avec au plus `limit` tâches actives à la fois.

    `limit=None` utilise `fanout_concurrency()`. Préserve l'ordre des résultats.
    """
    sem = asyncio.Semaphore(limit if limit is not None else fanout_concurrency())

    async def _run(aw: Awaitable[_T]) -> _T:
        from agent.core.pipeline_cancel import raise_if_pipeline_cancelled

        await raise_if_pipeline_cancelled()
        async with sem:
            await raise_if_pipeline_cancelled()
            return await aw

    return await asyncio.gather(
        *(_run(aw) for aw in awaitables), return_exceptions=return_exceptions
    )


async def count_running_pipelines(
    channel_id: uuid.UUID,
    *,
    exclude_project_id: uuid.UUID | None = None,
) -> int:
    async with AsyncSessionFactory() as session:
        query = (
            select(func.count())
            .select_from(Project)
            .where(Project.channel_id == channel_id, Project.status == "running")
        )
        if exclude_project_id is not None:
            query = query.where(Project.id != exclude_project_id)
        result = await session.execute(query)
        return int(result.scalar_one())


async def can_start_pipeline(
    channel_id: uuid.UUID,
    *,
    exclude_project_id: uuid.UUID | None = None,
) -> bool:
    async with AsyncSessionFactory() as session:
        channel_result = await session.execute(
            select(Channel.max_concurrent_pipelines).where(Channel.id == channel_id)
        )
        max_slots = channel_result.scalar_one_or_none() or 1

    running = await count_running_pipelines(
        channel_id, exclude_project_id=exclude_project_id
    )
    return running < max_slots


async def try_claim_project(project_id: uuid.UUID, channel_id: uuid.UUID) -> bool:
    """Passe atomiquement un projet queued → running si un slot chaîne est libre."""
    async with AsyncSessionFactory() as session:
        channel_result = await session.execute(
            select(Channel.max_concurrent_pipelines).where(Channel.id == channel_id)
        )
        max_slots = channel_result.scalar_one_or_none() or 1

        running_subq = (
            select(func.count())
            .select_from(Project)
            .where(
                Project.channel_id == channel_id,
                Project.status == "running",
                Project.id != project_id,
            )
            .scalar_subquery()
        )

        result = await session.execute(
            update(Project)
            .where(
                Project.id == project_id,
                Project.status == "queued",
                running_subq < max_slots,
            )
            .values(status="running", error_message=None)
        )
        await session.commit()
        return result.rowcount == 1
