from __future__ import annotations

import logging
import shutil
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, UTC
from pathlib import Path

from sqlalchemy import or_, select

from agent.core.config import get_storage_settings
from agent.core.database import AsyncSessionFactory, Project, Publication, Video

logger = logging.getLogger(__name__)


@dataclass
class PurgeReport:
    s3_deleted: int = 0
    videos_purged: int = 0
    dirs_removed: int = 0
    projects_purged: int = 0
    bytes_freed: int = 0
    errors: list[str] = field(default_factory=list)

    def merge(self, other: PurgeReport) -> None:
        self.s3_deleted += other.s3_deleted
        self.videos_purged += other.videos_purged
        self.dirs_removed += other.dirs_removed
        self.projects_purged += other.projects_purged
        self.bytes_freed += other.bytes_freed
        self.errors.extend(other.errors)

    def to_dict(self) -> dict:
        return asdict(self)


# Une vidéo publiée, en cours de publication ou programmée garde son fichier.
PROTECTED_PUBLICATION_STATUSES = ("scheduled", "publishing", "published")
# Projets dont la création n'est pas terminée : on ne touche pas à leurs fichiers.
# `paused` : création en attente du reset de la limite d'usage Claude (run dir à garder pour la reprise).
ACTIVE_PROJECT_STATUSES = ("running", "queued", "paused")


async def purge_video_files(videos: list[Video]) -> PurgeReport:
    from agent.core.storage import delete_s3_object

    report = PurgeReport()
    now = datetime.now(UTC)

    for video in videos:
        try:
            freed = video.file_size_bytes or 0
            if video.storage_key:
                await delete_s3_object(video.storage_key)
                report.s3_deleted += 1
                report.bytes_freed += freed
            if video.local_path:
                Path(video.local_path).unlink(missing_ok=True)
            report.videos_purged += 1

            async with AsyncSessionFactory() as session:
                db_video = await session.get(Video, video.id)
                if db_video:
                    db_video.file_purged_at = now
                    session.add(db_video)
                    await session.commit()
        except Exception as e:
            report.errors.append(f"{video.id}: {e}")
            logger.warning("Erreur purge vidéo %s : %s", video.id, e)

    return report


async def purge_oldest_until_free(target_free_bytes: int) -> int:
    async with AsyncSessionFactory() as session:
        result = await session.execute(
            select(Video)
            .where(Video.file_purged_at.is_(None))
            .where(Video.storage_key.isnot(None))
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


async def purge_project_files(project_id: uuid.UUID) -> PurgeReport:
    """Supprime les fichiers d'un projet sauf ses vidéos publiées / programmées.

    Dossiers de travail (tmp, sortie et run dir Studio) et vidéos finales non
    publiées (S3 + local, `file_purged_at` posé). Les lignes en base (vidéos,
    scénario, critiques) restent : la page projet bascule sur le repli DB.
    """
    from agent.core.pipeline_reset import studio_dirs

    protected = select(Publication.video_id).where(
        Publication.status.in_(PROTECTED_PUBLICATION_STATUSES)
    )
    async with AsyncSessionFactory() as session:
        result = await session.execute(
            select(Video).where(
                Video.project_id == project_id,
                Video.file_purged_at.is_(None),
                or_(Video.storage_key.isnot(None), Video.local_path.isnot(None)),
                Video.id.not_in(protected),
            )
        )
        videos = list(result.scalars().all())

    report = await purge_video_files(videos)
    for directory in (Path(f"./tmp/{project_id}"), *studio_dirs(project_id)):
        if not directory.exists():
            continue
        try:
            shutil.rmtree(directory)
            report.dirs_removed += 1
        except OSError as e:
            report.errors.append(f"{directory}: {e}")
    if report.dirs_removed or report.videos_purged:
        report.projects_purged = 1
    return report


async def purge_old_media_files(
    work_files_days: int | None = None,
    media_days: int | None = None,
) -> PurgeReport:
    """Purge planifiée.

    - projets terminés depuis `work_files_days` (défaut 7) : `purge_project_files()` ;
    - toutes les vidéos (publiées comprises) plus vieilles que `media_days`
      (défaut `storage.retention_days`).
    """
    from agent.scheduler.config import PURGE_DEFAULT_PARAMS

    work_days = PURGE_DEFAULT_PARAMS["work_files_days"] if work_files_days is None else work_files_days
    days = get_storage_settings().retention_days if media_days is None else media_days
    now = datetime.now(UTC)
    cutoff = now - timedelta(days=days)

    async with AsyncSessionFactory() as session:
        result = await session.execute(
            select(Video).where(
                Video.created_at < cutoff,
                Video.file_purged_at.is_(None),
            )
        )
        old_videos = list(result.scalars().all())

    report = await purge_video_files(old_videos)
    report.merge(await _purge_finished_projects(now - timedelta(days=work_days)))

    logger.info(
        "Purge planifiée (fichiers %d j, vidéos %d j) : projets=%d vidéos=%d s3=%d octets=%d dossiers=%d",
        work_days,
        days,
        report.projects_purged,
        report.videos_purged,
        report.s3_deleted,
        report.bytes_freed,
        report.dirs_removed,
    )
    return report


async def _purge_finished_projects(cutoff: datetime) -> PurgeReport:
    """Projets non actifs dont la dernière modification est antérieure à `cutoff`."""
    report = PurgeReport()
    async with AsyncSessionFactory() as session:
        result = await session.execute(
            select(Project.id).where(
                Project.updated_at < cutoff,
                Project.status.notin_(ACTIVE_PROJECT_STATUSES),
            )
        )
        project_ids = list(result.scalars().all())

    for project_id in project_ids:
        try:
            report.merge(await purge_project_files(project_id))
        except Exception as e:
            report.errors.append(f"{project_id}: {e}")
            logger.warning("Purge du projet %s échouée : %s", project_id, e)
    return report
