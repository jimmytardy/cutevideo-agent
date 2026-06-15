from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select

from agent.core.concurrency import can_start_pipeline
from agent.core.config import settings
from agent.core.database import AsyncSessionFactory, Project
from agent.core.pipeline_launcher import enqueue_pipeline
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
    launched = 0
    errors = 0

    async with AsyncSessionFactory() as session:
        result = await session.execute(
            select(Project)
            .where(Project.status == "pending")
            .order_by(Project.created_at.asc())
        )
        all_pending = list(result.scalars().all())

    pending = [p for p in all_pending if _project_targets_publication_date(p, target_iso)]
    launched_channels: set[Any] = set()

    for project in pending:
        if project.channel_id in launched_channels:
            continue
        if not await can_start_pipeline(project.channel_id):
            continue
        logger.info(
            "Lancement pipeline projet %s (publication cible %s, chaîne %s)",
            project.id,
            target_iso,
            project.channel_id,
        )
        await enqueue_pipeline(project.id)
        launched_channels.add(project.channel_id)
        launched += 1

    return {"launched": launched, "errors": errors, "target_publish_date": target_iso}


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
    {"id": "content_planner_daily", "name": "Content Planner", "schedule": "6h00 Europe/Paris"},
    {"id": "run_pending_projects_morning", "name": "Pipelines (matin)", "schedule": "6h30 Europe/Paris"},
    {"id": "run_pending_projects_hourly", "name": "Pipelines (horaire)", "schedule": "7h-23h Europe/Paris"},
    {"id": "distribution_agent", "name": "Distribution", "schedule": "*/15 min"},
    {"id": "engagement_agents_biweekly", "name": "Engagement", "schedule": "Lun/Jeu 9h15 Europe/Paris"},
    {"id": "purge_old_media", "name": "Purge médias", "schedule": "3h00 UTC"},
]
