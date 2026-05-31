from __future__ import annotations

import asyncio
import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import select

from agent.core.concurrency import can_start_pipeline
from agent.core.config import settings
from agent.core.database import AsyncSessionFactory, Project
from agent.core.orchestrator import Orchestrator
from agent.scheduler.cleanup import purge_old_media_files

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()


def setup_scheduler() -> None:
    """Configure les tâches planifiées."""
    scheduler.add_job(
        run_content_planner,
        CronTrigger(hour=6, minute=0, timezone="Europe/Paris"),
        id="content_planner_daily",
        replace_existing=True,
    )
    scheduler.add_job(
        run_pending_projects,
        CronTrigger(hour=6, minute=30, timezone="Europe/Paris"),
        id="run_pending_projects_morning",
        replace_existing=True,
    )
    scheduler.add_job(
        run_pending_projects,
        CronTrigger(hour="7-23", minute="0"),
        id="run_pending_projects_hourly",
        replace_existing=True,
    )
    scheduler.add_job(
        run_distribution_agent,
        CronTrigger(minute="*/15"),
        id="distribution_agent",
        replace_existing=True,
    )
    scheduler.add_job(
        run_engagement_agents,
        CronTrigger(day_of_week="mon,thu", hour=9, minute=15, timezone="Europe/Paris"),
        id="engagement_agents_biweekly",
        replace_existing=True,
    )
    scheduler.add_job(
        purge_old_media_files,
        CronTrigger(hour="3", minute="0"),
        id="purge_old_media",
        replace_existing=True,
        kwargs={"retention_days": settings.storage_retention_days},
    )
    logger.info("Scheduler configuré")


async def run_content_planner() -> None:
    """Planification éditoriale quotidienne (sujets longs + shorts)."""
    from agent.agents.content_planner_agent import ContentPlannerAgent

    await ContentPlannerAgent().run_scheduled()


async def run_distribution_agent() -> None:
    """Planification et publication des vidéos approuvées."""
    from agent.agents.distribution_agent import DistributionAgent

    await DistributionAgent().run_scheduled()


async def run_pending_projects() -> None:
    """Lance les projets en attente pour publication le lendemain (production J → publication J+1)."""
    from agent.scheduler.editorial_calendar import publication_target_iso

    target_iso = publication_target_iso()

    async with AsyncSessionFactory() as session:
        result = await session.execute(
            select(Project)
            .where(Project.status == "pending")
            .order_by(Project.created_at.asc())
        )
        all_pending = list(result.scalars().all())

    pending = [
        p
        for p in all_pending
        if _project_targets_publication_date(p, target_iso)
    ]

    launched_channels: set = set()

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
        asyncio.create_task(Orchestrator().run_pipeline(project.id))
        launched_channels.add(project.channel_id)


def _project_targets_publication_date(project: Project, target_iso: str) -> bool:
    pub = (project.config or {}).get("target_publish_date")
    if pub:
        return pub == target_iso
    return True


async def run_engagement_agents() -> None:
    """Agents post-publication : analytics et commentaires (lun/jeu, règles + Sonnet ciblé)."""
    from agent.agents.analytics_agent import AnalyticsAgent
    from agent.agents.comments_agent import CommentsAgent

    analytics_result = await AnalyticsAgent().run_scheduled()
    comments_result = await CommentsAgent().run_scheduled()
    logger.info(
        "Engagement terminé — analytics: %s, comments: %s",
        analytics_result,
        comments_result,
    )


async def main() -> None:
    setup_scheduler()
    scheduler.start()
    logger.info("Scheduler démarré")
    try:
        while True:
            await asyncio.sleep(3600)
    except (KeyboardInterrupt, SystemExit):
        scheduler.shutdown()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
