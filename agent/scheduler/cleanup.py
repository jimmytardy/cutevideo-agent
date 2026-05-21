from __future__ import annotations

import logging
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import select

from agent.core.config import get_storage_settings
from agent.core.database import AsyncSessionFactory, Project, Video

logger = logging.getLogger(__name__)


@dataclass
class PurgeReport:
    s3_deleted: int = 0
    local_deleted: int = 0
    dirs_removed: int = 0
    bytes_freed: int = 0
    errors: list[str] = field(default_factory=list)


async def purge_video_files(videos: list[Video]) -> PurgeReport:
    from agent.core.storage import delete_s3_object, is_s3_enabled

    report = PurgeReport()
    now = datetime.now(timezone.utc)

    for video in videos:
        try:
            freed = video.file_size_bytes or 0
            if video.storage_key and is_s3_enabled():
                await delete_s3_object(video.storage_key)
                report.s3_deleted += 1
                report.bytes_freed += freed

            if video.local_path:
                path = Path(video.local_path)
                if path.exists():
                    size = path.stat().st_size
                    path.unlink()
                    report.local_deleted += 1
                    if not video.storage_key:
                        report.bytes_freed += size

            async with AsyncSessionFactory() as session:
                db_video = await session.get(Video, video.id)
                if db_video:
                    db_video.file_purged_at = now
                    session.add(db_video)
                    await session.commit()
        except OSError as e:
            report.errors.append(f"{video.id}: {e}")
            logger.warning("Erreur purge vidéo %s : %s", video.id, e)

    return report


async def purge_oldest_until_free(target_free_bytes: int) -> int:
    async with AsyncSessionFactory() as session:
        result = await session.execute(
            select(Video)
            .where(Video.file_purged_at.is_(None))
            .where((Video.storage_key.isnot(None)) | (Video.local_path.isnot(None)))
            .order_by(Video.created_at.asc())
        )
        candidates = list(result.scalars().all())

    freed = 0
    for video in candidates:
        if freed >= target_free_bytes:
            break
        sub = await purge_video_files([video])
        freed += sub.bytes_freed

    logger.info("Purge quota : %d octets libérés (cible %d)", freed, target_free_bytes)
    return freed


async def purge_old_media_files(retention_days: int | None = None) -> PurgeReport:
    cfg = get_storage_settings()
    days = retention_days if retention_days is not None else cfg.retention_days
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    async with AsyncSessionFactory() as session:
        result = await session.execute(
            select(Video).where(
                Video.created_at < cutoff,
                Video.file_purged_at.is_(None),
            )
        )
        old_videos = list(result.scalars().all())

    report = await purge_video_files(old_videos)
    dirs_report = await _purge_old_project_dirs(cutoff)
    report.dirs_removed = dirs_report.dirs_removed
    report.errors.extend(dirs_report.errors)

    logger.info(
        "Purge planifiée (%d j) : s3=%d local=%d octets=%d dossiers=%d",
        days,
        report.s3_deleted,
        report.local_deleted,
        report.bytes_freed,
        report.dirs_removed,
    )
    return report


async def _purge_old_project_dirs(cutoff: datetime) -> PurgeReport:
    report = PurgeReport()

    async with AsyncSessionFactory() as session:
        projects_result = await session.execute(select(Project))
        projects = list(projects_result.scalars().all())

    for project in projects:
        created = project.created_at
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        if created > cutoff:
            continue

        project_id = str(project.id)
        tmp_dir = Path(f"./tmp/{project_id}")
        if tmp_dir.exists():
            try:
                shutil.rmtree(tmp_dir)
                report.dirs_removed += 1
            except OSError as e:
                report.errors.append(f"tmp/{project_id}: {e}")

        for pattern_dir in (
            Path("./output/long"),
            Path("./output/shorts/youtube"),
            Path("./output/shorts/tiktok"),
            Path("./output/shorts/instagram"),
        ):
            if not pattern_dir.exists():
                continue
            for f in pattern_dir.glob(f"*{project_id}*"):
                try:
                    if f.is_file():
                        f.unlink()
                    elif f.is_dir():
                        shutil.rmtree(f)
                    report.dirs_removed += 1
                except OSError as e:
                    report.errors.append(str(f))

    return report
