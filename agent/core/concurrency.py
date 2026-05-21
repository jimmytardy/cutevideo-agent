from __future__ import annotations

import uuid

from sqlalchemy import func, select

from agent.core.database import AsyncSessionFactory, Channel, Project


async def count_running_pipelines(channel_id: uuid.UUID) -> int:
    async with AsyncSessionFactory() as session:
        result = await session.execute(
            select(func.count())
            .select_from(Project)
            .where(Project.channel_id == channel_id, Project.status == "running")
        )
        return int(result.scalar_one())


async def can_start_pipeline(channel_id: uuid.UUID) -> bool:
    async with AsyncSessionFactory() as session:
        channel_result = await session.execute(
            select(Channel.max_concurrent_pipelines).where(Channel.id == channel_id)
        )
        max_slots = channel_result.scalar_one_or_none() or 1

    running = await count_running_pipelines(channel_id)
    return running < max_slots
