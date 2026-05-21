from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select

from agent.core.database import (
    AsyncSessionFactory,
    Channel,
    Publication,
    Video,
)


@dataclass
class PublicationJob:
    publication: Publication
    channel: Channel
    project_id: uuid.UUID


async def list_published_publications() -> list[PublicationJob]:
    async with AsyncSessionFactory() as session:
        result = await session.execute(
            select(Publication, Channel, Video.project_id)
            .join(Channel, Publication.channel_id == Channel.id)
            .join(Video, Publication.video_id == Video.id)
            .where(
                Publication.status == "published",
                Publication.platform_video_id.isnot(None),
                Channel.is_active == True,  # noqa: E712
            )
        )
        jobs: list[PublicationJob] = []
        for pub, channel, project_id in result.all():
            jobs.append(
                PublicationJob(
                    publication=pub,
                    channel=channel,
                    project_id=project_id,
                )
            )
        return jobs


def current_utc_hour() -> int:
    return datetime.now(timezone.utc).hour
