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
        run_pending_projects,
        CronTrigger(hour="*", minute="0"),
        id="run_pending_projects",
        replace_existing=True,
    )
    scheduler.add_job(
        run_engagement_agents,
        CronTrigger(hour="*", minute="15"),
        id="engagement_agents_hourly",
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


async def run_pending_projects() -> None:
    """Lance les projets en attente si la chaîne a un slot libre."""
    async with AsyncSessionFactory() as session:
        result = await session.execute(
            select(Project)
            .where(Project.status == "pending")
            .order_by(Project.created_at.asc())
        )
        pending = list(result.scalars().all())

    launched_channels: set = set()

    for project in pending:
        if project.channel_id in launched_channels:
            continue
        if not await can_start_pipeline(project.channel_id):
            continue

        logger.info(
            "Lancement automatique du projet %s (chaîne %s)",
            project.id,
            project.channel_id,
        )
        asyncio.create_task(Orchestrator().run_pipeline(project.id))
        launched_channels.add(project.channel_id)


async def run_engagement_agents() -> None:
    """Agents post-publication : analytics et commentaires (heures décalées par vidéo)."""
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
