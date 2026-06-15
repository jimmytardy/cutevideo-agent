#!/usr/bin/env python3
"""Worker Redis : exécute les pipelines hors du processus API uvicorn."""
from __future__ import annotations

import asyncio
import logging
import uuid

import redis.exceptions

from agent.core.orchestrator import Orchestrator
from agent.core.queue import PIPELINE_QUEUE, WORKER_BLPOP_TIMEOUT_S, queue

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


async def _process_task(payload: dict) -> None:
    project_id = uuid.UUID(payload["project_id"])
    start_from = payload.get("start_from")
    critic_feedback = payload.get("critic_feedback")
    critic_start_from = payload.get("critic_start_from")

    try:
        await Orchestrator().run_pipeline(
            project_id,
            start_from=start_from,
            critic_feedback=critic_feedback,
            critic_start_from=critic_start_from,
        )
    except asyncio.CancelledError:
        logger.info("Pipeline annulé pour le projet %s", project_id)
    except Exception as exc:
        logger.error("Pipeline échoué pour le projet %s : %s", project_id, exc, exc_info=True)
    finally:
        await queue.clear_pipeline_cancel(str(project_id))


async def run_worker() -> None:
    backoff_s = 2
    while True:
        try:
            await queue.connect()
            logger.info("Pipeline worker démarré — écoute sur %s", PIPELINE_QUEUE)
            backoff_s = 2
            while True:
                payload = await queue.pop_task(PIPELINE_QUEUE, timeout=WORKER_BLPOP_TIMEOUT_S)
                if payload is None:
                    continue
                logger.info("Tâche pipeline reçue : %s", payload.get("project_id"))
                await _process_task(payload)
        except redis.exceptions.ConnectionError as exc:
            logger.warning(
                "Redis indisponible (%s) — reconnexion dans %ss",
                exc,
                backoff_s,
            )
            await queue.disconnect()
            await asyncio.sleep(backoff_s)
            backoff_s = min(backoff_s * 2, 30)
        except asyncio.CancelledError:
            await queue.disconnect()
            raise
        except Exception:
            await queue.disconnect()
            raise


def main() -> None:
    asyncio.run(run_worker())


if __name__ == "__main__":
    main()
