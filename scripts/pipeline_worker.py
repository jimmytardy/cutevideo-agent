#!/usr/bin/env python3
"""Worker Redis : exécute les pipelines hors du processus API uvicorn."""
from __future__ import annotations

import asyncio
import logging
import os
import signal
import uuid

import redis.exceptions

from agent.core.config import get_pipeline_settings
from agent.core.orchestrator import Orchestrator
from agent.core.pipeline_cancel import bind_project, unbind_project
from agent.core.pipeline_lease import (
    acquire_lease,
    get_lease_settings,
    release_lease,
    renew_lease,
)
from agent.core.pipeline_queue import dequeue_next_eligible, migrate_legacy_pipeline_queue
from agent.core.pipeline_reconcile import reconcile_orphan_running_projects
from agent.core.queue import queue
from agent.core.subprocess_registry import kill_all

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

WORKER_ID = os.environ.get("WORKER_ID", os.environ.get("HOSTNAME", "worker-1"))

_shutdown_event: asyncio.Event | None = None
_current_pipeline_task: asyncio.Task[None] | None = None


def _get_shutdown_event() -> asyncio.Event:
    global _shutdown_event
    if _shutdown_event is None:
        _shutdown_event = asyncio.Event()
    return _shutdown_event


def _request_shutdown() -> None:
    logger.info("[%s] Arrêt demandé (signal)", WORKER_ID)
    _get_shutdown_event().set()
    task = _current_pipeline_task
    if task is not None and not task.done():
        task.cancel()


async def _renew_lease_loop(
    project_id: uuid.UUID,
    worker_id: str,
    stop: asyncio.Event,
) -> None:
    _, renew_interval = get_lease_settings()
    while not stop.is_set():
        try:
            await asyncio.wait_for(stop.wait(), timeout=renew_interval)
            return
        except asyncio.TimeoutError:
            if not await renew_lease(project_id, worker_id):
                logger.warning(
                    "[%s] Renouvellement lease perdu pour le projet %s",
                    worker_id,
                    project_id,
                )
                return


async def _cancel_watcher(
    project_id: uuid.UUID,
    pipeline_task: asyncio.Task[None],
    stop: asyncio.Event,
    *,
    poll_interval_s: float = 0.5,
) -> None:
    while not stop.is_set() and not pipeline_task.done():
        if await queue.is_pipeline_cancel_requested(str(project_id)):
            logger.info("[%s] Annulation Redis détectée — projet %s", WORKER_ID, project_id)
            pipeline_task.cancel()
            return
        try:
            await asyncio.wait_for(stop.wait(), timeout=poll_interval_s)
            return
        except asyncio.TimeoutError:
            continue


async def _process_task(payload: dict) -> None:
    global _current_pipeline_task

    project_id = uuid.UUID(payload["project_id"])
    start_from = payload.get("start_from")
    critic_feedback = payload.get("critic_feedback")
    critic_start_from = payload.get("critic_start_from")
    resume_iteration = payload.get("resume_iteration")

    await acquire_lease(project_id, WORKER_ID)
    stop_renew = asyncio.Event()
    renew_task = asyncio.create_task(_renew_lease_loop(project_id, WORKER_ID, stop_renew))

    project_token = bind_project(project_id)
    pipeline_task = asyncio.create_task(
        Orchestrator().run_pipeline(
            project_id,
            start_from=start_from,
            critic_feedback=critic_feedback,
            critic_start_from=critic_start_from,
            resume_iteration=resume_iteration,
            already_claimed=True,
        )
    )
    _current_pipeline_task = pipeline_task
    stop_watcher = asyncio.Event()
    watcher_task = asyncio.create_task(
        _cancel_watcher(project_id, pipeline_task, stop_watcher)
    )

    try:
        await pipeline_task
    except asyncio.CancelledError:
        logger.info("[%s] Pipeline annulé pour le projet %s", WORKER_ID, project_id)
    except Exception as exc:
        logger.error(
            "[%s] Pipeline échoué pour le projet %s : %s",
            WORKER_ID,
            project_id,
            exc,
            exc_info=True,
        )
    finally:
        stop_watcher.set()
        watcher_task.cancel()
        try:
            await watcher_task
        except asyncio.CancelledError:
            pass
        _current_pipeline_task = None
        stop_renew.set()
        renew_task.cancel()
        try:
            await renew_task
        except asyncio.CancelledError:
            pass
        unbind_project(project_token)
        await kill_all()
        await release_lease(project_id, WORKER_ID)
        await queue.clear_pipeline_cancel(str(project_id))


async def _periodic_reconcile_loop(worker_id: str) -> None:
    cfg = get_pipeline_settings()
    shutdown = _get_shutdown_event()
    while not shutdown.is_set():
        try:
            await asyncio.wait_for(shutdown.wait(), timeout=cfg.reconcile_interval_seconds)
            return
        except asyncio.TimeoutError:
            pass
        try:
            count = await reconcile_orphan_running_projects(worker_id=worker_id)
            if count:
                logger.info(
                    "[%s] Réconciliation périodique : %d projet(s) remis en file",
                    worker_id,
                    count,
                )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning(
                "[%s] Réconciliation périodique échouée : %s",
                worker_id,
                exc,
                exc_info=True,
            )


async def _sleep_or_shutdown(seconds: float) -> bool:
    """Attend ``seconds`` ou jusqu'à shutdown. Retourne True si shutdown demandé."""
    shutdown = _get_shutdown_event()
    if shutdown.is_set():
        return True
    try:
        await asyncio.wait_for(shutdown.wait(), timeout=seconds)
        return True
    except asyncio.TimeoutError:
        return False


async def run_worker() -> None:
    cfg = get_pipeline_settings()
    backoff_s = 2
    blocked_backoff_s = cfg.queue_blocked_backoff_seconds
    shutdown = _get_shutdown_event()

    while not shutdown.is_set():
        try:
            await queue.connect()
            migrated = await migrate_legacy_pipeline_queue()
            if migrated:
                logger.info("[%s] %d tâche(s) migrée(s) depuis l'ancienne queue", WORKER_ID, migrated)
            reconciled = await reconcile_orphan_running_projects(worker_id=WORKER_ID)
            if reconciled:
                logger.info(
                    "[%s] Réconciliation au démarrage : %d projet(s) remis en file",
                    WORKER_ID,
                    reconciled,
                )
            logger.info("[%s] Pipeline worker démarré", WORKER_ID)
            backoff_s = 2
            reconcile_task = asyncio.create_task(_periodic_reconcile_loop(WORKER_ID))
            try:
                while not shutdown.is_set():
                    result = await dequeue_next_eligible()
                    if result.payload is None:
                        sleep_s = blocked_backoff_s if result.all_blocked else 1
                        if await _sleep_or_shutdown(sleep_s):
                            break
                        continue
                    logger.info(
                        "[%s] Tâche pipeline reçue : %s",
                        WORKER_ID,
                        result.payload.get("project_id"),
                    )
                    await _process_task(result.payload)
            finally:
                reconcile_task.cancel()
                try:
                    await reconcile_task
                except asyncio.CancelledError:
                    pass
        except redis.exceptions.ConnectionError as exc:
            if shutdown.is_set():
                break
            logger.warning(
                "[%s] Redis indisponible (%s) — reconnexion dans %ss",
                WORKER_ID,
                exc,
                backoff_s,
            )
            await queue.disconnect()
            if await _sleep_or_shutdown(backoff_s):
                break
            backoff_s = min(backoff_s * 2, 30)
        except asyncio.CancelledError:
            await queue.disconnect()
            raise
        except Exception:
            await queue.disconnect()
            raise

    await queue.disconnect()
    logger.info("[%s] Pipeline worker arrêté", WORKER_ID)


async def _run_with_signals() -> None:
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, _request_shutdown)
        except NotImplementedError:
            pass
    await run_worker()


def main() -> None:
    asyncio.run(_run_with_signals())


if __name__ == "__main__":
    main()
