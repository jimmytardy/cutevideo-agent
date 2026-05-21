from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import TYPE_CHECKING

from agent.core.config import get_storage_settings

if TYPE_CHECKING:
    from agent.core.database import Video

logger = logging.getLogger(__name__)


class StorageQuotaExceededError(RuntimeError):
    """Impossible de libérer assez d'espace S3 pour l'upload."""


def is_s3_enabled() -> bool:
    cfg = get_storage_settings()
    return cfg.backend == "s3" and bool(cfg.bucket)


def build_storage_key(
    channel_slug: str,
    project_id: str,
    video_type: str,
    video_id: str,
) -> str:
    cfg = get_storage_settings()
    prefix = cfg.key_prefix.strip("/")
    safe_type = (video_type or "video").replace("/", "_")
    parts = [p for p in (prefix, channel_slug, project_id, safe_type, f"{video_id}.mp4") if p]
    return "/".join(parts)


async def get_used_bytes() -> int:
    from sqlalchemy import func, select

    from agent.core.database import AsyncSessionFactory, Video

    async with AsyncSessionFactory() as session:
        result = await session.execute(
            select(func.coalesce(func.sum(Video.file_size_bytes), 0)).where(
                Video.storage_key.isnot(None),
                Video.file_purged_at.is_(None),
            )
        )
        return int(result.scalar_one())


async def delete_s3_object(storage_key: str) -> None:
    if not storage_key or not is_s3_enabled():
        return

    def _delete() -> None:
        import boto3

        cfg = get_storage_settings()
        region = cfg.region if cfg.region and cfg.region != "auto" else "auto"
        client_kwargs: dict = {"region_name": region}
        if cfg.endpoint_url:
            client_kwargs["endpoint_url"] = cfg.endpoint_url
        client = boto3.client("s3", **client_kwargs)
        client.delete_object(Bucket=cfg.bucket, Key=storage_key)

    await asyncio.get_event_loop().run_in_executor(None, _delete)
    logger.info("S3 objet supprimé : %s", storage_key)


async def upload_file(local_path: Path, storage_key: str) -> None:
    def _upload() -> None:
        import boto3

        cfg = get_storage_settings()
        region = cfg.region if cfg.region and cfg.region != "auto" else "auto"
        client_kwargs: dict = {"region_name": region}
        if cfg.endpoint_url:
            client_kwargs["endpoint_url"] = cfg.endpoint_url
        client = boto3.client("s3", **client_kwargs)
        client.upload_file(
            str(local_path),
            cfg.bucket,
            storage_key,
            ExtraArgs={"ContentType": "video/mp4"},
        )

    await asyncio.get_event_loop().run_in_executor(None, _upload)
    logger.info("S3 upload OK : %s -> %s", local_path, storage_key)


async def get_presigned_url(storage_key: str, ttl_seconds: int | None = None) -> str:
    cfg = get_storage_settings()
    ttl = ttl_seconds or cfg.presign_ttl_seconds

    def _presign() -> str:
        import boto3

        region = cfg.region if cfg.region and cfg.region != "auto" else "auto"
        client_kwargs: dict = {"region_name": region}
        if cfg.endpoint_url:
            client_kwargs["endpoint_url"] = cfg.endpoint_url
        client = boto3.client("s3", **client_kwargs)
        return client.generate_presigned_url(
            "get_object",
            Params={"Bucket": cfg.bucket, "Key": storage_key},
            ExpiresIn=ttl,
        )

    return await asyncio.get_event_loop().run_in_executor(None, _presign)


async def ensure_capacity(required_bytes: int) -> None:
    if not is_s3_enabled():
        return

    cfg = get_storage_settings()
    used = await get_used_bytes()
    target_free = required_bytes + cfg.storage_buffer_bytes
    if used + target_free <= cfg.max_storage_bytes:
        return

    need_to_free = (used + target_free) - cfg.max_storage_bytes
    logger.warning(
        "Quota S3 presque atteint (used=%d, need=%d) — purge des plus anciennes vidéos",
        used,
        need_to_free,
    )

    from agent.scheduler.cleanup import purge_oldest_until_free

    freed = await purge_oldest_until_free(need_to_free)
    if freed < need_to_free:
        raise StorageQuotaExceededError(
            f"Impossible de libérer {need_to_free} octets (libéré {freed}). "
            "Augmentez S3_MAX_STORAGE_BYTES ou réduisez STORAGE_RETENTION_DAYS."
        )


async def get_public_video_url_async(video: Video) -> str:
    if video.storage_key and is_s3_enabled():
        return await get_presigned_url(video.storage_key)
    if video.local_path and Path(video.local_path).exists():
        from agent.skills.publisher.composio_client import build_public_video_url

        return build_public_video_url(str(video.project_id), Path(video.local_path))
    raise RuntimeError(f"Aucune source vidéo disponible pour {video.id}")


async def persist_video_to_storage(
    video: Video,
    channel_slug: str,
    local_path: Path,
) -> Video:
    from agent.core.database import AsyncSessionFactory

    file_size = local_path.stat().st_size

    if not is_s3_enabled():
        async with AsyncSessionFactory() as session:
            from sqlalchemy import update

            from agent.core.database import Video as VideoModel

            await session.execute(
                update(VideoModel)
                .where(VideoModel.id == video.id)
                .values(file_size_bytes=file_size)
            )
            await session.commit()
            refreshed = await session.get(VideoModel, video.id)
            if refreshed:
                return refreshed
        return video

    storage_key = build_storage_key(
        channel_slug=channel_slug,
        project_id=str(video.project_id),
        video_type=video.video_type or "video",
        video_id=str(video.id),
    )

    await ensure_capacity(file_size)
    await upload_file(local_path, storage_key)

    cfg = get_storage_settings()
    if cfg.delete_local_after_upload and local_path.exists():
        local_path.unlink()
        logger.debug("Fichier local supprimé après upload : %s", local_path)

    async with AsyncSessionFactory() as session:
        from sqlalchemy import update

        from agent.core.database import Video as VideoModel

        await session.execute(
            update(VideoModel)
            .where(VideoModel.id == video.id)
            .values(storage_key=storage_key, file_size_bytes=file_size)
        )
        await session.commit()
        result = await session.get(VideoModel, video.id)
        if result:
            return result

    return video


async def resolve_local_path_for_upload(video: Video) -> Path:
    """Chemin local pour YouTube : fichier local ou téléchargement temporaire depuis S3."""
    if video.local_path and Path(video.local_path).exists():
        return Path(video.local_path)
    if video.storage_key and is_s3_enabled():
        tmp_dir = Path(f"./tmp/download/{video.id}")
        tmp_dir.mkdir(parents=True, exist_ok=True)
        dest = tmp_dir / "video.mp4"

        def _download() -> None:
            import boto3

            cfg = get_storage_settings()
            client_kwargs: dict = {"region_name": cfg.region}
            if cfg.endpoint_url:
                client_kwargs["endpoint_url"] = cfg.endpoint_url
            client = boto3.client("s3", **client_kwargs)
            client.download_file(cfg.bucket, video.storage_key, str(dest))

        await asyncio.get_event_loop().run_in_executor(None, _download)
        return dest
    raise RuntimeError(f"Aucun fichier disponible pour la vidéo {video.id}")
