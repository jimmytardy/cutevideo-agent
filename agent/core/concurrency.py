from __future__ import annotations

import uuid

from sqlalchemy import func, select

from agent.core.database import AsyncSessionFactory, Channel, Project


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
