from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import select

from agent.core.channel_config import ChannelRuntimeConfig
from agent.core.config import settings
from agent.core.database import AsyncSessionFactory, Channel, Publication, Video
from agent.core.storage import get_public_video_url_async, resolve_local_path_for_upload
from agent.skills.publisher import composio_client

logger = logging.getLogger(__name__)


def platform_for_video_type(video_type: str | None) -> str | None:
    vtype = video_type or "long"
    if vtype in ("long", "youtube", "short_youtube"):
        return "youtube"
    if vtype in ("short_tiktok", "tiktok"):
        return "tiktok"
    if vtype in ("short_instagram", "instagram"):
        return "instagram"
    return None


def is_long_video_type(video_type: str | None) -> bool:
    return (video_type or "long") == "long"


def channel_supports_platform(channel: Channel, platform: str) -> bool:
    if platform == "youtube":
        return bool(channel.youtube_channel_id)
    if platform == "tiktok":
        return composio_client.tiktok_is_connected(channel)
    if platform == "instagram":
        return bool(channel.instagram_page_id)
    return False


async def publish_scheduled(
    publication: Publication,
    channel: Channel,
    channel_config: ChannelRuntimeConfig,
    video: Video,
) -> Publication | None:
    """Exécute l'upload pour une publication planifiée et met à jour la ligne en DB."""
    platform = (publication.platform or "").lower()
    title = publication.title or "Vidéo éducative"
    description = publication.description or ""
    tags = list(publication.hashtags or channel_config.default_tags)

    if video.file_purged_at:
        await _mark_failed(publication.id, "video_file_purged")
        return None
    if not video.storage_key:
        await _mark_failed(publication.id, "video_file_missing")
        return None

    await _mark_publishing(publication.id)

    try:
        if platform == "youtube":
            return await _publish_youtube(
                publication, channel, channel_config, video, title, description, tags
            )
        if platform == "tiktok":
            return await _publish_tiktok(publication, channel, video, title)
        if platform == "instagram":
            return await _publish_instagram(publication, channel, video, title, tags)
        await _mark_failed(publication.id, f"unknown_platform:{platform}")
        return None
    except Exception as e:
        logger.warning(
            "Publication %s échouée (%s/%s) : %s",
            publication.id,
            channel.slug,
            platform,
            e,
        )
        await _mark_failed(publication.id, str(e))
        return None


async def _publish_youtube(
    publication: Publication,
    channel: Channel,
    channel_config: ChannelRuntimeConfig,
    video: Video,
    title: str,
    description: str,
    tags: list[str],
) -> Publication | None:
    import tempfile

    from agent.skills.publisher.thumbnail import generate_thumbnail
    from agent.skills.publisher.youtube import set_thumbnail, upload_video
    from agent.skills.publisher.youtube_channel_manager import post_publish_hook

    video_path = await resolve_local_path_for_upload(video)
    refresh_token = channel.youtube_refresh_token or settings.youtube_refresh_token
    video_id = await upload_video(
        video_path=video_path,
        title=title,
        description=description,
        tags=tags,
        category_id=channel_config.youtube_category_id,
        refresh_token=refresh_token,
    )
    pub = await _mark_published(
        publication.id,
        platform_video_id=video_id,
        platform_url=f"https://youtube.com/watch?v={video_id}",
    )

    try:
        with tempfile.TemporaryDirectory() as tmp:
            thumbnail_path = await generate_thumbnail(
                title=title,
                theme=channel.theme_category or description[:80],
                output_dir=Path(tmp),
                ai_cfg=channel_config.ai_fallback,
                editorial_tone=channel_config.editorial_tone,
                aspect_ratio="16:9",
            )
            if thumbnail_path:
                await set_thumbnail(video_id, thumbnail_path, refresh_token=refresh_token)
    except Exception as e:
        logger.warning("Miniature YouTube non définie (non bloquant) : %s", e)

    # Récupère le thème via le projet pour la playlist
    try:
        from sqlalchemy import select

        from agent.core.database import AsyncSessionFactory, Project

        async with AsyncSessionFactory() as db:
            result = await db.execute(select(Project).where(Project.id == video.project_id))
            project = result.scalar_one_or_none()
            theme = project.theme if project else (channel.theme_category or "général")
            # Recharge le channel dans cette session pour pouvoir modifier channel.config
            from agent.core.database import Channel as ChannelModel
            ch_result = await db.execute(select(ChannelModel).where(ChannelModel.id == channel.id))
            ch = ch_result.scalar_one_or_none()
            if ch:
                await post_publish_hook(ch, video_id, theme, db)
    except Exception as e:
        logger.warning("post_publish_hook YouTube échoué (non bloquant) : %s", e)

    return pub


async def _publish_tiktok(
    publication: Publication,
    channel: Channel,
    video: Video,
    caption: str,
) -> Publication | None:
    video_url = await get_public_video_url_async(video)
    publish_id = await composio_client.publish_tiktok_video(
        channel=channel,
        video_url=video_url,
        caption=caption,
    )
    return await _mark_published(
        publication.id,
        platform_video_id=publish_id,
        platform_url=None,
    )


async def _publish_instagram(
    publication: Publication,
    channel: Channel,
    video: Video,
    caption: str,
    tags: list[str],
) -> Publication | None:
    from agent.skills.publisher.instagram import upload_reel

    video_url = await get_public_video_url_async(video)
    local_path = await resolve_local_path_for_upload(video)
    media_id = await upload_reel(
        video_path=local_path,
        caption=caption,
        hashtags=tags,
        video_url=video_url,
        page_id=channel.instagram_page_id or settings.instagram_page_id,
    )
    if not media_id:
        await _mark_failed(publication.id, "instagram_upload_no_media_id")
        return None
    return await _mark_published(
        publication.id,
        platform_video_id=media_id,
        platform_url=None,
    )


async def _mark_publishing(publication_id: uuid.UUID) -> None:
    async with AsyncSessionFactory() as session:
        result = await session.execute(
            select(Publication).where(Publication.id == publication_id)
        )
        pub = result.scalar_one_or_none()
        if pub:
            pub.status = "publishing"
            await session.commit()


async def _mark_failed(publication_id: uuid.UUID, error: str) -> None:
    async with AsyncSessionFactory() as session:
        result = await session.execute(
            select(Publication).where(Publication.id == publication_id)
        )
        pub = result.scalar_one_or_none()
        if pub:
            pub.status = "failed"
            reason = dict(pub.scheduling_reason or {})
            reason["error"] = error
            pub.scheduling_reason = reason
            await session.commit()


async def _mark_published(
    publication_id: uuid.UUID,
    platform_video_id: str,
    platform_url: str | None,
) -> Publication:
    async with AsyncSessionFactory() as session:
        result = await session.execute(
            select(Publication).where(Publication.id == publication_id)
        )
        pub = result.scalar_one_or_none()
        if not pub:
            raise ValueError(f"Publication {publication_id} introuvable")
        pub.platform_video_id = platform_video_id
        pub.platform_url = platform_url
        pub.published_at = datetime.now(timezone.utc)
        pub.status = "published"
        await session.commit()
        await session.refresh(pub)
        return pub
