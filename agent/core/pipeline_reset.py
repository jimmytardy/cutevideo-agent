"""Cleanup utilities for restarting a pipeline from a specific step.

Calling cleanup_from_step(project_id, step, session) deletes all DB artifacts
produced by `step` and every subsequent step, then resets agent-run statuses.
S3 objects are deleted for any Video rows being removed.

delete_project_completely() removes every artifact for a project (DB, fichiers, Redis).
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
    MontagePlan,
    PlatformComment,
    Publication,
    Scenario,
    Video,
)
from agent.core.queue import queue
from agent.core.storage import delete_s3_object

logger = logging.getLogger(__name__)

# Ordered pipeline steps — the index drives what gets deleted
PIPELINE_STEPS: list[str] = [
    "research_agent",        # 0
    "scenario_agent",        # 1
    "hook_optimizer_agent",    # 2
    "narrator_agent",        # 3
    "beat_planner_agent",    # 4
    "media_agent",           # 5
    "montage_planner_agent", # 6
    "editor_agent",          # 7
    "subtitle_agent",        # 8
    "critic_agent",          # 9
    "clipper_agent",         # 10
    "short_editor_agent",    # 11
]

# Shown in the UI between scenario and media during critic revision loops.
_REVISION_AGENT = "revision_agent"

_PRE_MEDIA_AGENTS: list[str] = [
    "fact_checker_agent",
    "hook_optimizer_agent",
]

# subtitle_agent re-bakes the video file via ffmpeg, so restarting from it
# is equivalent to restarting from editor_agent (we must recreate the Video row).
_EFFECTIVE_STEP: dict[str, str] = {
    "subtitle_agent": "editor_agent",
    "revision_agent": "narrator_agent",
    "diagram_specialist_agent": "beat_planner_agent",
    # outline_agent (P2) précède le scénariste : le réinitialiser revient à repartir du
    # scénario (l'outline persisté dans project.config est réécrit au prochain run).
    "outline_agent": "scenario_agent",
}

# Étapes autorisées pour POST /run-from/{step} (revision_agent = boucle critique).
RUN_FROM_STEPS: frozenset[str] = frozenset([*PIPELINE_STEPS, "revision_agent"])


def step_index(step: str) -> int:
    effective = _EFFECTIVE_STEP.get(step, step)
    return PIPELINE_STEPS.index(effective)


async def cleanup_from_step(
    project_id: uuid.UUID,
    step: str,
    session: AsyncSession,
) -> None:
    """Delete all artifacts from `step` onwards for the given project."""
    if step not in PIPELINE_STEPS:
        raise ValueError(f"Étape inconnue : {step!r}. Valeurs valides : {PIPELINE_STEPS}")

    idx = step_index(step)
    logger.info("Nettoyage projet %s depuis l'étape %s (idx=%d)", project_id, step, idx)

    # --- critic_agent: delete CriticReports BEFORE videos to avoid FK violation ---
    if idx <= 9:
        video_ids_q = await session.execute(
            select(Video.id).where(Video.project_id == project_id)
        )
        video_ids = [r[0] for r in video_ids_q.all()]
        if video_ids:
            await session.execute(
                delete(CriticReport).where(CriticReport.video_id.in_(video_ids))
            )

    # --- short_editor_agent: delete short_* videos ---
    if idx <= 11:
        short_vids_result = await session.execute(
            select(Video).where(
                Video.project_id == project_id,
                Video.video_type.like("short_%"),
            )
        )
        for v in short_vids_result.scalars().all():
            if v.storage_key:
                await delete_s3_object(v.storage_key)
            await session.delete(v)

    # --- editor_agent / subtitle_agent: delete main videos (long, short_master) ---
    if idx <= 7:
        main_vids_result = await session.execute(
            select(Video).where(
                Video.project_id == project_id,
                Video.video_type.in_(["long", "short_master"]),
            )
        )
        for v in main_vids_result.scalars().all():
            if v.storage_key:
                await delete_s3_object(v.storage_key)
            await session.delete(v)

    # --- montage_planner_agent: delete MontagePlan ---
    if idx <= 6:
        await session.execute(
            delete(MontagePlan).where(MontagePlan.project_id == project_id)
        )

    # --- narrator_agent: delete AudioFiles ---
    if idx <= 3:
        await session.execute(
            delete(AudioFile).where(AudioFile.project_id == project_id)
        )

    # --- media_agent / beat_planner_agent: delete MediaAssets ---
    if idx <= 5:
        await session.execute(
            delete(MediaAsset).where(MediaAsset.project_id == project_id)
        )

    # --- scenario_agent: delete Scenarios ---
    if idx <= 1:
        await session.execute(
            delete(Scenario).where(Scenario.project_id == project_id)
        )

    # --- research_agent: clear research_brief from project config ---
    if idx == 0:
        from agent.core.database import Project
        from sqlalchemy import update as sa_update

        project = await session.get(Project, project_id)
        if project and project.config:
            cfg = dict(project.config)
            cfg.pop("research_brief", None)
            await session.execute(
                sa_update(Project).where(Project.id == project_id).values(config=cfg)
            )

    # --- Delete AgentRun rows for affected steps ---
    affected_steps = PIPELINE_STEPS[idx:]
    agent_names_to_clear = list(affected_steps)
    # Revision runs during critic loops before media; stale status if we re-run that segment.
    if idx <= 7:
        agent_names_to_clear.append(_REVISION_AGENT)
    if idx <= 2:
        agent_names_to_clear.extend(
            agent for agent in _PRE_MEDIA_AGENTS if agent not in agent_names_to_clear
        )

    await session.execute(
        delete(AgentRun).where(
            AgentRun.project_id == project_id,
            AgentRun.agent_name.in_(agent_names_to_clear),
        )
    )

    # --- Reset Redis status dots (UI reads these, not AgentRun rows) ---
    await queue.clear_agent_statuses(str(project_id), agent_names_to_clear)

    await session.flush()
    logger.info("Nettoyage terminé pour le projet %s depuis %s", project_id, step)


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

    await queue.clear_agent_statuses(str(project_id))

    tmp_dir = Path(f"./tmp/{project_id}")
    if tmp_dir.exists():
        shutil.rmtree(tmp_dir)

    await session.flush()
    logger.info("Artefacts supprimés pour le projet %s", project_id)
