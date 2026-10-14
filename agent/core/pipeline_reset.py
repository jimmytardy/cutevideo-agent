"""Nettoyage des artefacts d'un projet.

- `clear_creation_artifacts()` : avant une (re)création Claude Studio, supprime
  les vidéos non publiées, critiques, scénarios et runs de la création précédente.
- `delete_project_completely()` : supprime tout (DB, S3, fichiers, Redis).
"""
from __future__ import annotations

import logging
import shutil
import uuid
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from agent.core.database import (
    AgentRun,
    Analytics,
    AudioFile,
    CriticReport,
    MediaAsset,
    PlatformComment,
    Publication,
    Scenario,
    Video,
)
from agent.core.storage import delete_s3_object

logger = logging.getLogger(__name__)

def _studio_dirs(project_id: uuid.UUID) -> list[Path]:
    from agent.core.claude_studio import OUTPUT_ROOT
    from studio.launcher import default_runs_dir

    return [OUTPUT_ROOT / str(project_id), default_runs_dir() / str(project_id)]


async def clear_creation_artifacts(project_id: uuid.UUID, session: AsyncSession) -> None:
    """Efface la création précédente ; les vidéos déjà publiées/planifiées sont conservées."""
    published = select(Publication.video_id).where(Publication.video_id.is_not(None))
    videos_result = await session.execute(
        select(Video).where(Video.project_id == project_id, Video.id.not_in(published))
    )
    videos = list(videos_result.scalars().all())
    video_ids = [v.id for v in videos]
    if video_ids:
        await session.execute(delete(CriticReport).where(CriticReport.video_id.in_(video_ids)))
    for video in videos:
        if video.storage_key:
            try:
                await delete_s3_object(video.storage_key)
            except Exception as exc:
                # Un objet S3 orphelin ne doit pas bloquer la nouvelle création.
                logger.warning("Suppression S3 échouée (%s) : %s", video.storage_key, exc)
        await session.delete(video)
    await session.execute(delete(Scenario).where(Scenario.project_id == project_id))
    await session.execute(delete(AgentRun).where(AgentRun.project_id == project_id))
    await session.flush()


def _unlink_if_exists(path: Path) -> None:
    if path.exists():
        path.unlink()


async def delete_project_completely(
    project_id: uuid.UUID,
    session: AsyncSession,
) -> None:
    """Supprime tous les artefacts d'un projet (DB, S3, fichiers locaux, Redis)."""
    logger.info("Suppression complète du projet %s", project_id)

    video_ids_result = await session.execute(
        select(Video.id).where(Video.project_id == project_id)
    )
    video_ids = [row[0] for row in video_ids_result.all()]

    if video_ids:
        pub_ids_result = await session.execute(
            select(Publication.id).where(Publication.video_id.in_(video_ids))
        )
        pub_ids = [row[0] for row in pub_ids_result.all()]

        if pub_ids:
            await session.execute(
                delete(PlatformComment).where(PlatformComment.publication_id.in_(pub_ids))
            )
            await session.execute(
                delete(Analytics).where(Analytics.publication_id.in_(pub_ids))
            )

        await session.execute(delete(Publication).where(Publication.video_id.in_(video_ids)))
        await session.execute(delete(CriticReport).where(CriticReport.video_id.in_(video_ids)))

        videos_result = await session.execute(
            select(Video).where(Video.project_id == project_id)
        )
        for video in videos_result.scalars().all():
            if video.storage_key:
                await delete_s3_object(video.storage_key)
            if video.local_path:
                _unlink_if_exists(Path(video.local_path))
            await session.delete(video)

    audio_paths_result = await session.execute(
        select(AudioFile.local_path).where(AudioFile.project_id == project_id)
    )
    for (local_path,) in audio_paths_result.all():
        if local_path:
            _unlink_if_exists(Path(local_path))

    media_paths_result = await session.execute(
        select(MediaAsset.local_path).where(MediaAsset.project_id == project_id)
    )
    for (local_path,) in media_paths_result.all():
        if local_path:
            _unlink_if_exists(Path(local_path))

    await session.execute(delete(AudioFile).where(AudioFile.project_id == project_id))
    await session.execute(delete(MediaAsset).where(MediaAsset.project_id == project_id))
    await session.execute(delete(Scenario).where(Scenario.project_id == project_id))
    await session.execute(delete(AgentRun).where(AgentRun.project_id == project_id))


    for directory in [Path(f"./tmp/{project_id}"), *_studio_dirs(project_id)]:
        if directory.exists():
            shutil.rmtree(directory)

    await session.flush()
    logger.info("Artefacts supprimés pour le projet %s", project_id)
