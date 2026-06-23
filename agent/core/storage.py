from __future__ import annotations

import asyncio
import logging
import uuid
from pathlib import Path
from typing import TYPE_CHECKING

from agent.core.config import get_storage_settings

if TYPE_CHECKING:
    from agent.core.database import Video

logger = logging.getLogger(__name__)


class StorageQuotaExceededError(RuntimeError):
    """Impossible de libérer assez d'espace S3 pour l'upload."""


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


async def generate_presigned_url(storage_key: str, expires_in: int = 3600) -> str:
    def _generate() -> str:
        client, cfg = _make_s3_client()
        return client.generate_presigned_url(
            "get_object",
            Params={"Bucket": cfg.bucket, "Key": storage_key},
            ExpiresIn=expires_in,
        )

    return await asyncio.get_event_loop().run_in_executor(None, _generate)


async def delete_s3_object(storage_key: str) -> None:
    if not storage_key:
        return

    def _delete() -> None:
        client, cfg = _make_s3_client()
        client.delete_object(Bucket=cfg.bucket, Key=storage_key)

    await asyncio.get_event_loop().run_in_executor(None, _delete)
    logger.info("S3 objet supprimé : %s", storage_key)


def _make_s3_client() -> tuple:
    import boto3

    cfg = get_storage_settings()
    region = cfg.region if cfg.region and cfg.region != "auto" else "auto"
    client_kwargs: dict = {"region_name": region}
    if cfg.endpoint_url:
        client_kwargs["endpoint_url"] = cfg.endpoint_url
    return boto3.client("s3", **client_kwargs), cfg


def _ensure_bucket(client, bucket: str, region: str) -> None:
    from botocore.exceptions import ClientError

    try:
        client.head_bucket(Bucket=bucket)
    except ClientError as e:
        code = e.response["Error"]["Code"]
        if code in ("404", "NoSuchBucket"):
            kwargs: dict = {}
            if region and region != "auto":
                kwargs["CreateBucketConfiguration"] = {"LocationConstraint": region}
            client.create_bucket(Bucket=bucket, **kwargs)
            logger.info("Bucket S3 créé : %s", bucket)
        else:
            raise


def is_s3_storage_enabled() -> bool:
    return bool(get_storage_settings().bucket)


async def upload_file(local_path: Path, storage_key: str) -> None:
    await upload_media_file(local_path, storage_key, content_type="video/mp4")


async def upload_media_file(
    local_path: Path,
    storage_key: str,
    *,
    content_type: str = "application/octet-stream",
) -> int:
    file_size = local_path.stat().st_size

    def _upload() -> None:
        client, cfg = _make_s3_client()
        _ensure_bucket(client, cfg.bucket, cfg.region)
        client.upload_file(
            str(local_path),
            cfg.bucket,
            storage_key,
            ExtraArgs={"ContentType": content_type},
        )

    await asyncio.get_event_loop().run_in_executor(None, _upload)
    logger.info("S3 upload OK : %s -> %s", local_path, storage_key)
    return file_size


def build_temp_ai_storage_key(
    channel_slug: str,
    project_id: str,
    segment_order: int,
    candidate_id: str,
) -> str:
    cfg = get_storage_settings()
    prefix = cfg.key_prefix.strip("/")
    parts = [
        p
        for p in (
            prefix,
            "temp",
            channel_slug,
            project_id,
            "ai",
            str(segment_order),
            f"{candidate_id}.jpg",
        )
        if p
    ]
    return "/".join(parts)


async def delete_s3_objects(keys: list[str]) -> None:
    for key in keys:
        if key:
            await delete_s3_object(key)


async def register_temp_ai_key(project_id: uuid.UUID, key: str) -> None:
    if not key:
        return
    from sqlalchemy import select

    from agent.core.database import AsyncSessionFactory, Project

    async with AsyncSessionFactory() as session:
        result = await session.execute(select(Project).where(Project.id == project_id))
        project = result.scalar_one_or_none()
        if project is None:
            return
        config = dict(project.config or {})
        keys = list(config.get("temp_ai_image_keys") or [])
        if key not in keys:
            keys.append(key)
        config["temp_ai_image_keys"] = keys
        project.config = config
        await session.commit()


async def cleanup_temp_ai_images(
    project_id: uuid.UUID,
    *,
    keep_keys: list[str] | None = None,
) -> None:
    from sqlalchemy import select

    from agent.core.database import AsyncSessionFactory, Project

    async with AsyncSessionFactory() as session:
        result = await session.execute(select(Project).where(Project.id == project_id))
        project = result.scalar_one_or_none()
        if project is None:
            return
        config = dict(project.config or {})
        registered = list(config.get("temp_ai_image_keys") or [])
        keep = set(keep_keys or [])
        to_delete = [k for k in registered if k not in keep]
        if is_s3_storage_enabled() and to_delete:
            await delete_s3_objects(to_delete)
        remaining = [k for k in registered if k in keep] if keep_keys is not None else []
        if keep_keys is None:
            remaining = []
        config["temp_ai_image_keys"] = remaining
        project.config = config
        await session.commit()
        if to_delete:
            logger.info(
                "Temp AI images purgées pour projet %s : %d clé(s)",
                project_id,
                len(to_delete),
            )


async def get_presigned_url(storage_key: str, ttl_seconds: int | None = None) -> str:
    cfg = get_storage_settings()
    ttl = ttl_seconds or cfg.presign_ttl_seconds

    def _presign() -> str:
        client, cfg = _make_s3_client()
        return client.generate_presigned_url(
            "get_object",
            Params={"Bucket": cfg.bucket, "Key": storage_key},
            ExpiresIn=ttl,
        )

    return await asyncio.get_event_loop().run_in_executor(None, _presign)


async def download_storage_key(storage_key: str, dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)

    def _download() -> None:
        client, cfg = _make_s3_client()
        client.download_file(cfg.bucket, storage_key, str(dest))

    await asyncio.get_event_loop().run_in_executor(None, _download)
    return dest


async def ensure_capacity(required_bytes: int) -> None:
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
    if not video.storage_key:
        raise RuntimeError(f"Aucune clé S3 pour la vidéo {video.id}")
    return await get_presigned_url(video.storage_key)


async def cleanup_local_videos_for_project(project_id: uuid.UUID) -> None:
    """Supprime les fichiers locaux uploadés sur S3 (après la boucle critique)."""
    from sqlalchemy import select

    from agent.core.database import AsyncSessionFactory, Video

    cfg = get_storage_settings()
    if not cfg.delete_local_after_upload:
        return

    async with AsyncSessionFactory() as session:
        result = await session.execute(select(Video).where(Video.project_id == project_id))
        videos = list(result.scalars().all())

    for video in videos:
        if not video.storage_key or not video.local_path:
            continue
        local = Path(video.local_path)
        if local.exists():
            local.unlink()
            logger.debug("Fichier local supprimé (post-critique) : %s", local)


async def persist_video_to_storage(
    video: Video,
    channel_slug: str,
    local_path: Path,
    *,
    delete_local: bool | None = None,
) -> Video:
    from agent.core.database import AsyncSessionFactory

    file_size = local_path.stat().st_size

    storage_key = build_storage_key(
        channel_slug=channel_slug,
        project_id=str(video.project_id),
        video_type=video.video_type or "video",
        video_id=str(video.id),
    )

    await ensure_capacity(file_size)
    await upload_file(local_path, storage_key)

    cfg = get_storage_settings()
    should_delete = cfg.delete_local_after_upload if delete_local is None else delete_local
    if should_delete and local_path.exists():
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
    """Télécharge depuis S3 vers un fichier temporaire local pour l'upload plateforme."""
    if not video.storage_key:
        raise RuntimeError(f"Aucune clé S3 pour la vidéo {video.id}")

    tmp_dir = Path(f"./tmp/download/{video.id}")
    tmp_dir.mkdir(parents=True, exist_ok=True)
    dest = tmp_dir / "video.mp4"

    def _download() -> None:
        client, cfg = _make_s3_client()
        client.download_file(cfg.bucket, video.storage_key, str(dest))

    await asyncio.get_event_loop().run_in_executor(None, _download)
    return dest


async def check_s3_connectivity() -> tuple[bool, str | None]:
    """Vérifie que le bucket S3 est accessible. Retourne (ok, detail)."""
    cfg = get_storage_settings()
    if not cfg.bucket:
        return False, "S3_BUCKET non configuré"
    try:
        def _check() -> None:
            client, c = _make_s3_client()
            # Crée le bucket s'il est absent (404), comme le ferait le premier
            # upload via _ensure_bucket — sinon le health check reste "error"
            # tant qu'aucune vidéo n'a été uploadée.
            _ensure_bucket(client, c.bucket, c.region)

        await asyncio.get_event_loop().run_in_executor(None, _check)
        return True, None
    except Exception as e:
        return False, str(e)
