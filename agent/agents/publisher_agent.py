from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select

from agent.core.base_agent import BaseAgent
from agent.core.config import settings
from agent.core.database import AsyncSessionFactory, Publication, Scenario, Video
from agent.core.storage import get_public_video_url_async, resolve_local_path_for_upload
from agent.skills.publisher import composio_client

logger = logging.getLogger(__name__)


class PublisherAgent(BaseAgent):
    """Agent 9 — Publisher : publie les vidéos sur YouTube, TikTok (Composio) et Instagram."""

    name = "publisher_agent"

    async def run(self, ctx: "PipelineContext") -> list[Publication]:  # type: ignore[override]
        run = await self.start_run(ctx.project_id, {"channel": ctx.channel_slug})
        publications: list[Publication] = []
        try:
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
                )
                scenario = scenario_result.scalar_one_or_none()

            title = "Vidéo éducative"
            description = ctx.theme
            tags = ctx.channel_config.default_tags
            if scenario and scenario.segments:
                first = scenario.segments[0] if isinstance(scenario.segments, list) else {}
                title = str(first.get("title", title)) if isinstance(first, dict) else title

            for video in videos:
                if video.file_purged_at:
                    continue
                if not video.storage_key and not (video.local_path and Path(video.local_path).exists()):
                    continue

                vtype = video.video_type or "long"

                if vtype in ("long", "youtube", "short_youtube") and ctx.channel.youtube_channel_id:
                    pub = await self._publish_youtube(ctx, video, title, description, tags)
                    if pub:
                        publications.append(pub)

                if vtype in ("short_tiktok", "tiktok") and composio_client.tiktok_is_connected(ctx.channel):
                    pub = await self._publish_tiktok(ctx, video, title)
                    if pub:
                        publications.append(pub)

                if vtype in ("short_instagram", "instagram") and ctx.channel.instagram_page_id:
                    pub = await self._publish_instagram(ctx, video, title, tags)
                    if pub:
                        publications.append(pub)

            await self.end_run(run, {"publications": len(publications)})
            return publications
        except Exception as e:
            await self.fail_run(run, e)
            raise

    async def _publish_youtube(
        self,
        ctx: "PipelineContext",
        video: Video,
        title: str,
        description: str,
        tags: list[str],
    ) -> Publication | None:
        try:
            from agent.skills.publisher.youtube import upload_video

            video_path = await resolve_local_path_for_upload(video)
            video_id = await upload_video(
                video_path=video_path,
                title=title,
                description=description,
                tags=tags,
                category_id=ctx.channel_config.youtube_category_id,
                refresh_token=ctx.channel.youtube_refresh_token or settings.youtube_refresh_token,
            )
            return await self._save_publication(
                ctx, video, "youtube", video_id, f"https://youtube.com/watch?v={video_id}", title, description, tags
            )
        except Exception as e:
            logger.warning("Publication YouTube ignorée (%s) : %s", ctx.channel.slug, e)
            return None

    async def _publish_tiktok(self, ctx: "PipelineContext", video: Video, caption: str) -> Publication | None:
        try:
            video_url = await get_public_video_url_async(video)
            publish_id = await composio_client.publish_tiktok_video(
                channel=ctx.channel,
                video_url=video_url,
                caption=caption,
            )
            return await self._save_publication(
                ctx, video, "tiktok", publish_id, None, caption, "", []
            )
        except Exception as e:
            logger.warning("Publication TikTok ignorée (%s) : %s", ctx.channel.slug, e)
            return None

    async def _publish_instagram(
        self,
        ctx: "PipelineContext",
        video: Video,
        caption: str,
        tags: list[str],
    ) -> Publication | None:
        try:
            from agent.skills.publisher.instagram import upload_reel

            video_url = await get_public_video_url_async(video)
            local_path = await resolve_local_path_for_upload(video)
            media_id = await upload_reel(
                video_path=local_path,
                caption=caption,
                hashtags=tags,
                video_url=video_url,
                page_id=ctx.channel.instagram_page_id or settings.instagram_page_id,
            )
            if not media_id:
                return None
            return await self._save_publication(
                ctx, video, "instagram", media_id, None, caption, "", tags
            )
        except Exception as e:
            logger.warning("Publication Instagram ignorée (%s) : %s", ctx.channel.slug, e)
            return None

    async def _save_publication(
        self,
        ctx: "PipelineContext",
        video: Video,
        platform: str,
        platform_video_id: str,
        platform_url: str | None,
        title: str,
        description: str,
        hashtags: list[str],
    ) -> Publication:
        async with AsyncSessionFactory() as session:
            pub = Publication(
                video_id=video.id,
                channel_id=ctx.channel_id,
                platform=platform,
                platform_video_id=platform_video_id,
                platform_url=platform_url,
                title=title,
                description=description,
                hashtags=hashtags,
                published_at=datetime.now(timezone.utc),
                status="published",
            )
            session.add(pub)
            await session.commit()
            await session.refresh(pub)
            return pub
