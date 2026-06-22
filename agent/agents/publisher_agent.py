from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select

from agent.core.base_agent import BaseAgent
from agent.core.channel_config import resolve_channel_config
from agent.core.channel_config import ChannelRuntimeConfig
from agent.core.database import AsyncSessionFactory, Channel, Publication, Scenario, Video
from agent.skills.publisher.executor import (
    channel_supports_platform,
    platform_for_video_type,
    publish_scheduled,
)

logger = logging.getLogger(__name__)


class PublisherAgent(BaseAgent):
    """Agent legacy — publication immédiate (préférer distribution_agent en production)."""

    name = "publisher_agent"

    async def run(self, ctx: "PipelineContext") -> list[Publication]:  # type: ignore[override]
        run = await self.start_run(ctx.project_id, {"channel": ctx.channel_slug})
        publications: list[Publication] = []
        try:
            channel_config = ctx.channel_config
            async with AsyncSessionFactory() as session:
                videos_result = await session.execute(
                    select(Video)
                    .where(Video.project_id == ctx.project_id)
                    .order_by(Video.created_at.desc())
                )
                videos = list(videos_result.scalars().all())

                scenario_result = await session.execute(
                    select(Scenario)
                    .where(Scenario.project_id == ctx.project_id)
                    .order_by(Scenario.created_at.desc())
                    .limit(1)
                )
                scenario = scenario_result.scalar_one_or_none()

            title = "Vidéo éducative"
            description = ctx.theme
            tags = channel_config.default_tags
            if scenario and scenario.segments:
                first = scenario.segments[0] if isinstance(scenario.segments, list) else {}
                title = str(first.get("title", title)) if isinstance(first, dict) else title

            now = datetime.now(timezone.utc)
            for video in videos:
                if video.file_purged_at:
                    continue
                if not video.storage_key:
                    continue

                platform = platform_for_video_type(video.video_type)
                if not platform or not channel_supports_platform(ctx.channel, platform):
                    continue

                pub = await self._create_and_publish(
                    video=video,
                    channel_id=ctx.channel_id,
                    channel=ctx.channel,
                    channel_config=channel_config,
                    platform=platform,
                    title=title,
                    description=description,
                    tags=tags,
                    scheduled_at=now,
                )
                if pub and pub.status == "published":
                    publications.append(pub)

            await self.end_run(run, {"publications": len(publications)})
            return publications
        except Exception as e:
            await self.fail_run(run, e)
            raise

    @staticmethod
    async def _create_and_publish(
        video: Video,
        channel_id: uuid.UUID,
        channel: Channel,
        channel_config: ChannelRuntimeConfig,
        platform: str,
        title: str,
        description: str,
        tags: list[str],
        scheduled_at: datetime,
    ) -> Publication | None:
        async with AsyncSessionFactory() as session:
            pub = Publication(
                video_id=video.id,
                channel_id=channel_id,
                platform=platform,
                title=title,
                description=description,
                hashtags=tags,
                scheduled_at=scheduled_at,
                status="scheduled",
                scheduling_reason={"source": "publisher_agent_immediate"},
            )
            session.add(pub)
            await session.commit()
            await session.refresh(pub)

        return await publish_scheduled(pub, channel, channel_config, video)
