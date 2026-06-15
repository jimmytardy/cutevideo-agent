from __future__ import annotations

import uuid

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agent.core.database import Channel, Project, User


async def get_user_channel(
    db: AsyncSession, channel_id: uuid.UUID, user: User
) -> Channel:
    result = await db.execute(
        select(Channel).where(Channel.id == channel_id, Channel.user_id == user.id)
    )
    channel = result.scalar_one_or_none()
    if channel is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chaîne introuvable")
    return channel


async def get_user_project(
    db: AsyncSession, project_id: uuid.UUID, user: User
) -> Project:
    result = await db.execute(
        select(Project)
        .join(Channel, Channel.id == Project.channel_id)
        .where(Project.id == project_id, Channel.user_id == user.id)
    )
    project = result.scalar_one_or_none()
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Projet introuvable")
    return project
