from __future__ import annotations

import asyncio
import logging
from typing import Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import select

from agent.core.config import settings
from agent.core.database import AsyncSessionFactory, SchedulerRun
from agent.scheduler import jobs
from agent.scheduler.config import (
    JobConfig,
    load_job_configs,
    load_scheduler_enabled,
    save_job_config,
    save_scheduler_enabled,
)

logger = logging.getLogger(__name__)


class SchedulerService:
    """Service centralisé pour les tâches planifiées."""

    def __init__(self) -> None:
        self._scheduler = AsyncIOScheduler()
        self._running = False
        self._background_tasks: set[asyncio.Task[Any]] = set()

    @property
    def running(self) -> bool:
        return self._running and self._scheduler.running

    @property
    def process_allowed(self) -> bool:
        """`SCHEDULER_ENABLED=false` interdit le scheduler dans ce processus, quelle que soit la base."""
        return settings.scheduler_enabled

    async def setup(self) -> None:
        configs = await load_job_configs()
        for job_id, fn in jobs.JOB_REGISTRY.items():
            self._apply_job(job_id, fn, configs[job_id])
        logger.info(
            "Scheduler configuré (%d/%d jobs actifs)",
            sum(c.enabled for c in configs.values()),
            len(jobs.JOB_REGISTRY),
        )

    def _apply_job(self, job_id: str, fn: Any, config: JobConfig) -> None:
        if self._scheduler.get_job(job_id):
            self._scheduler.remove_job(job_id)
        if config.enabled:
            self._scheduler.add_job(fn, config.trigger(), id=job_id, replace_existing=True)

    async def start_from_config(self) -> None:
        """Démarrage de l'API : selon la base, sauf veto du processus."""
        if not self.process_allowed:
            logger.info("Scheduler désactivé pour ce processus (SCHEDULER_ENABLED=false)")
            return
        if await load_scheduler_enabled():
            await self.start()

    async def set_enabled(self, enabled: bool) -> None:
        """Activation globale persistée en base, appliquée à chaud."""
        await save_scheduler_enabled(enabled)
        if enabled and self.process_allowed:
            await self.start()
        elif not enabled:
            await self.stop()

    async def start(self) -> None:
        if self._running:
            return
        await self.setup()
        self._scheduler.start()
        self._running = True
        logger.info("Scheduler démarré")

    async def stop(self) -> None:
        if not self._running:
            return
        self._scheduler.shutdown(wait=False)
        self._scheduler.remove_all_jobs()
        self._running = False
        logger.info("Scheduler arrêté")

    async def update_job(self, job_id: str, **changes: Any) -> JobConfig:
        """Enregistre la planification d'un job ; replanifie à chaud si le scheduler tourne."""
        config = await save_job_config(job_id, **changes)
        if self._running:
            self._apply_job(job_id, jobs.JOB_REGISTRY[job_id], config)
        return config

    async def get_status(self) -> dict[str, Any]:
        configs = await load_job_configs()
        job_statuses: list[dict[str, Any]] = []
        for meta in jobs.JOB_METADATA:
            job_id = meta["id"]
            config = configs[job_id]
            ap_job = self._scheduler.get_job(job_id)
            next_run = ap_job.next_run_time.isoformat() if ap_job and ap_job.next_run_time else None
            job_statuses.append({
                **meta,
                "schedule": f"{config.cron} ({config.timezone})",
                "enabled": config.enabled,
                "cron": config.cron,
                "timezone": config.timezone,
                "params": config.params,
                "next_run_at": next_run,
            })
        return {
            "running": self.running,
            "enabled": await load_scheduler_enabled(),
            "process_allowed": self.process_allowed,
            "jobs_count": len(jobs.JOB_REGISTRY),
            "jobs": job_statuses,
        }

    async def list_jobs_with_last_run(self) -> list[dict[str, Any]]:
        status = await self.get_status()
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


    def launch_job(self, job_id: str) -> dict[str, Any]:
        """Lance un job en tâche de fond et retourne immédiatement.

        Le job s'exécute « à la volée » sans bloquer l'appelant ; sa progression
        est suivie en base (SchedulerRun) via @track_job_run et visible dans
        l'historique. Le scheduler n'a pas besoin d'être démarré.
        """
        fn = jobs.JOB_REGISTRY.get(job_id)
        if fn is None:
            raise ValueError(f"Job inconnu : {job_id}")

        async def _runner() -> None:
            try:
                await fn()
            except Exception:  # déjà enregistré en base par @track_job_run
                logger.exception("Lancement manuel du job %s échoué", job_id)

        task = asyncio.create_task(_runner(), name=f"manual-job-{job_id}")
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)
        return {"job_id": job_id, "status": "started"}


scheduler_service = SchedulerService()
