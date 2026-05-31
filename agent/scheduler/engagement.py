from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from agent.core.database import (
    AsyncSessionFactory,
    Channel,
    Publication,
    Video,
)
SHORT_ANALYTICS_DAYS = 21
LONG_ANALYTICS_DAYS = 180
LONG_ANALYTICS_HISTORY_LIMIT = 90


@dataclass
class PublicationJob:
    publication: Publication
    channel: Channel
    project_id: uuid.UUID
    video_type: str | None = None


def analytics_window_days(video_type: str | None) -> int:
    if (video_type or "long") == "long":
        return LONG_ANALYTICS_DAYS
    if video_type and video_type.startswith("short"):
        return SHORT_ANALYTICS_DAYS
    return SHORT_ANALYTICS_DAYS


def analytics_history_limit(video_type: str | None) -> int:
    if (video_type or "long") == "long":
        return LONG_ANALYTICS_HISTORY_LIMIT
    return SHORT_ANALYTICS_DAYS


def is_within_engagement_window(
    published_at: datetime | None,
    video_type: str | None,
    *,
    force_all: bool = False,
) -> bool:
    if force_all:
        return True
    if not published_at:
        return False
    window_days = analytics_window_days(video_type)
    if published_at.tzinfo is None:
        published_at = published_at.replace(tzinfo=timezone.utc)
    cutoff = datetime.now(timezone.utc) - timedelta(days=window_days)
    return published_at >= cutoff


async def list_published_publications(*, force_all: bool = False) -> list[PublicationJob]:
    async with AsyncSessionFactory() as session:
        result = await session.execute(
            select(Publication, Channel, Video.project_id, Video.video_type)
            .join(Channel, Publication.channel_id == Channel.id)
            .join(Video, Publication.video_id == Video.id)
            .where(
                Publication.status == "published",
                Publication.platform_video_id.isnot(None),
                Channel.is_active == True,  # noqa: E712
            )
        )
        jobs: list[PublicationJob] = []
        for pub, channel, project_id, video_type in result.all():
            if not is_within_engagement_window(pub.published_at, video_type, force_all=force_all):
                continue
            jobs.append(
                PublicationJob(
                    publication=pub,
                    channel=channel,
                    project_id=project_id,
                    video_type=video_type,
                )
            )
        return jobs


def current_utc_hour() -> int:
    return datetime.now(timezone.utc).hour
