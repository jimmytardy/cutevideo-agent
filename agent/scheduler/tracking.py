from __future__ import annotations

import functools
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, TypeVar

from agent.core.database import AsyncSessionFactory, SchedulerRun

logger = logging.getLogger(__name__)

F = TypeVar("F", bound=Callable[..., Any])


def track_job_run(job_id: str) -> Callable[[F], F]:
    """Enregistre le début/fin d'un job planifié en base."""

    def decorator(fn: F) -> F:
        @functools.wraps(fn)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            run_id = uuid.uuid4()
            started = datetime.now(timezone.utc)
            async with AsyncSessionFactory() as session:
                session.add(
                    SchedulerRun(
                        id=run_id,
                        job_id=job_id,
                        status="running",
                        started_at=started,
                    )
                )
                await session.commit()

            try:
                result = await fn(*args, **kwargs)
                ended = datetime.now(timezone.utc)
                result_json = result if isinstance(result, dict) else {"result": str(result)}
                async with AsyncSessionFactory() as session:
                    run = await session.get(SchedulerRun, run_id)
                    if run:
                        run.status = "success"
                        run.ended_at = ended
                        run.result_json = result_json
                        await session.commit()
                return result
            except Exception as exc:
                ended = datetime.now(timezone.utc)
                async with AsyncSessionFactory() as session:
                    run = await session.get(SchedulerRun, run_id)
                    if run:
                        run.status = "failed"
                        run.ended_at = ended
                        run.error = str(exc)
                        await session.commit()
                logger.error("Job %s échoué : %s", job_id, exc)
                raise

        return wrapper  # type: ignore[return-value]

    return decorator
