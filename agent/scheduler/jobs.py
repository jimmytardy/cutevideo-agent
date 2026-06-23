from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select

from agent.core.config import settings
from agent.core.database import AsyncSessionFactory, Channel, Project
from agent.core.pipeline_launcher import enqueue_pipeline
from agent.core.pipeline_queue import PipelineAlreadyQueuedError, is_queued
from agent.scheduler.cleanup import purge_old_media_files
from agent.scheduler.editorial_calendar import publication_target_iso
from agent.scheduler.tracking import track_job_run

logger = logging.getLogger(__name__)


@track_job_run("content_planner_daily")
async def run_content_planner() -> dict[str, Any]:
    from agent.agents.content_planner_agent import ContentPlannerAgent

    return await ContentPlannerAgent().run_scheduled()


@track_job_run("distribution_agent")
async def run_distribution_agent() -> dict[str, Any]:
    from agent.agents.distribution_agent import DistributionAgent

    return await DistributionAgent().run_scheduled()


@track_job_run("run_pending_projects_morning")
async def run_pending_projects_morning() -> dict[str, int]:
    return await _run_pending_projects()


@track_job_run("run_pending_projects_hourly")
async def run_pending_projects_hourly() -> dict[str, int]:
    return await _run_pending_projects()


async def _run_pending_projects() -> dict[str, int]:
    target_iso = publication_target_iso()
    enqueued = 0
    skipped = 0
    errors = 0

    async with AsyncSessionFactory() as session:
        result = await session.execute(
            select(Project, Channel)
            .join(Channel, Channel.id == Project.channel_id)
            .where(Project.status == "pending")
            .order_by(Project.created_at.asc())
        )
        rows = list(result.all())

    pending = [(p, c) for p, c in rows if _project_targets_publication_date(p, target_iso)]

    for project, channel in pending:
        if await is_queued(project.id):
            skipped += 1
            continue
        try:
            logger.info(
                "Enqueue pipeline projet %s (publication cible %s, chaîne %s)",
                project.id,
                target_iso,
                project.channel_id,
            )
            await enqueue_pipeline(project.id, user_id=channel.user_id)
            enqueued += 1
        except PipelineAlreadyQueuedError:
            skipped += 1
        except Exception as exc:
            errors += 1
            logger.error("Enqueue échoué pour projet %s : %s", project.id, exc)

    return {
        "enqueued": enqueued,
        "skipped": skipped,
        "errors": errors,
        "target_publish_date": target_iso,
    }


def _project_targets_publication_date(project: Project, target_iso: str) -> bool:
    pub = (project.config or {}).get("target_publish_date")
    if pub:
        return pub == target_iso
    return True


@track_job_run("engagement_agents_biweekly")
async def run_engagement_agents() -> dict[str, Any]:
    from agent.agents.analytics_agent import AnalyticsAgent
    from agent.agents.comments_agent import CommentsAgent

    analytics_result = await AnalyticsAgent().run_scheduled()
    comments_result = await CommentsAgent().run_scheduled()
    return {"analytics": analytics_result, "comments": comments_result}


@track_job_run("purge_old_media")
async def run_purge_old_media() -> None:
    await purge_old_media_files(retention_days=settings.storage_retention_days)


JOB_REGISTRY: dict[str, Any] = {
    "content_planner_daily": run_content_planner,
    "run_pending_projects_morning": run_pending_projects_morning,
    "run_pending_projects_hourly": run_pending_projects_hourly,
    "distribution_agent": run_distribution_agent,
    "engagement_agents_biweekly": run_engagement_agents,
    "purge_old_media": run_purge_old_media,
}

JOB_METADATA: list[dict[str, str]] = [
    {
        "id": "content_planner_daily",
        "name": "Content Planner",
        "schedule": "6h00 Europe/Paris",
        "description": "Construit le plan éditorial du lendemain et crée les projets vidéo « en attente » pour chaque chaîne.",
    },
    {
        "id": "run_pending_projects_morning",
        "name": "Pipelines (matin)",
        "schedule": "6h30 Europe/Paris",
        "description": "Lance la pipeline de création des projets en attente dont la publication est prévue le jour cible.",
    },
    {
        "id": "run_pending_projects_hourly",
        "name": "Pipelines (horaire)",
        "schedule": "7h-23h Europe/Paris",
        "description": "Repasse sur les projets en attente non encore démarrés et lance leur pipeline de création.",
    },
    {
        "id": "distribution_agent",
        "name": "Distribution",
        "schedule": "*/15 min",
        "description": "Planifie et publie les vidéos approuvées sur les plateformes (YouTube, TikTok, Instagram).",
    },
    {
        "id": "engagement_agents_biweekly",
        "name": "Engagement",
        "schedule": "Lun/Jeu 9h15 Europe/Paris",
        "description": "Analyse les performances puis répond aux commentaires et met à jour le contexte d'apprentissage des chaînes.",
    },
    {
        "id": "purge_old_media",
        "name": "Purge médias",
        "schedule": "3h00 UTC",
        "description": "Nettoie le stockage en supprimant les fichiers médias qui dépassent la durée de rétention.",
    },
]
