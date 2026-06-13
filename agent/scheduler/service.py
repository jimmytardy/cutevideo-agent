from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import select

from agent.core.config import settings
from agent.core.database import AsyncSessionFactory, SchedulerRun
from agent.scheduler import jobs

logger = logging.getLogger(__name__)


class SchedulerService:
    """Service centralisé pour les tâches planifiées."""

    def __init__(self) -> None:
        self._scheduler = AsyncIOScheduler()
        self._running = False

    @property
    def running(self) -> bool:
        return self._running and self._scheduler.running

    def setup(self) -> None:
        self._scheduler.add_job(
            jobs.run_content_planner,
            CronTrigger(hour=6, minute=0, timezone="Europe/Paris"),
            id="content_planner_daily",
            replace_existing=True,
        )
        self._scheduler.add_job(
            jobs.run_pending_projects_morning,
            CronTrigger(hour=6, minute=30, timezone="Europe/Paris"),
            id="run_pending_projects_morning",
            replace_existing=True,
        )
        self._scheduler.add_job(
            jobs.run_pending_projects_hourly,
            CronTrigger(hour="7-23", minute="0"),
            id="run_pending_projects_hourly",
            replace_existing=True,
        )
        self._scheduler.add_job(
            jobs.run_distribution_agent,
            CronTrigger(minute="*/15"),
            id="distribution_agent",
            replace_existing=True,
        )
        self._scheduler.add_job(
            jobs.run_engagement_agents,
            CronTrigger(day_of_week="mon,thu", hour=9, minute=15, timezone="Europe/Paris"),
            id="engagement_agents_biweekly",
            replace_existing=True,
        )
        self._scheduler.add_job(
            jobs.run_purge_old_media,
            CronTrigger(hour="3", minute="0"),
            id="purge_old_media",
            replace_existing=True,
        )
        logger.info("Scheduler configuré (%d jobs)", len(jobs.JOB_REGISTRY))

    async def start(self) -> None:
        if self._running:
            return
        self.setup()
        self._scheduler.start()
        self._running = True
        logger.info("Scheduler démarré")

    async def stop(self) -> None:
        if not self._running:
            return
        self._scheduler.shutdown(wait=False)
        self._running = False
        logger.info("Scheduler arrêté")

    def get_status(self) -> dict[str, Any]:
        job_statuses: list[dict[str, Any]] = []
        for meta in jobs.JOB_METADATA:
            job_id = meta["id"]
            ap_job = self._scheduler.get_job(job_id)
            next_run = ap_job.next_run_time.isoformat() if ap_job and ap_job.next_run_time else None
            job_statuses.append({**meta, "next_run_at": next_run})
        return {
            "running": self.running,
            "jobs_count": len(jobs.JOB_REGISTRY),
            "jobs": job_statuses,
        }

    async def list_jobs_with_last_run(self) -> list[dict[str, Any]]:
        status = self.get_status()
        enriched: list[dict[str, Any]] = []
        for job in status["jobs"]:
            last = await self._last_run_for_job(job["id"])
            enriched.append({**job, "last_run": last})
        return enriched

    async def _last_run_for_job(self, job_id: str) -> dict[str, Any] | None:
        async with AsyncSessionFactory() as session:
            result = await session.execute(
                select(SchedulerRun)
                .where(SchedulerRun.job_id == job_id)
                .order_by(SchedulerRun.started_at.desc())
                .limit(1)
            )
            run = result.scalar_one_or_none()
        if not run:
            return None
        duration_s = None
        if run.started_at and run.ended_at:
            duration_s = (run.ended_at - run.started_at).total_seconds()
        return {
            "id": str(run.id),
            "status": run.status,
            "started_at": run.started_at.isoformat() if run.started_at else None,
            "ended_at": run.ended_at.isoformat() if run.ended_at else None,
            "duration_s": duration_s,
            "error": run.error,
        }

    async def list_runs(self, job_id: str | None = None, limit: int = 20) -> list[SchedulerRun]:
        async with AsyncSessionFactory() as session:
            query = select(SchedulerRun).order_by(SchedulerRun.started_at.desc()).limit(limit)
            if job_id:
                query = query.where(SchedulerRun.job_id == job_id)
            result = await session.execute(query)
            return list(result.scalars().all())

    async def run_job_now(self, job_id: str) -> dict[str, Any]:
        fn = jobs.JOB_REGISTRY.get(job_id)
        if fn is None:
            raise ValueError(f"Job inconnu : {job_id}")
        result = await fn()
        return {"job_id": job_id, "status": "completed", "result": result}


scheduler_service = SchedulerService()
