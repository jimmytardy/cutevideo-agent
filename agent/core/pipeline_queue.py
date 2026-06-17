from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select

from agent.core.concurrency import try_claim_project
from agent.core.config import get_pipeline_settings
from agent.core.database import AsyncSessionFactory, Channel, Project, User
from agent.core.disk_guard import format_disk_wait_message, is_disk_sufficient
from agent.core.pipeline_lease import has_active_lease
from agent.core.pipeline_resume import resolve_start_from
from agent.core.queue import (
    LEGACY_PIPELINE_QUEUE,
    PIPELINE_PAYLOAD_PREFIX,
    PIPELINE_ZQUEUE,
    queue,
)
from agent.core.subscription import resolve_user_limits

logger = logging.getLogger(__name__)

MAX_QUEUE_PRIORITY = 100
DEFAULT_QUEUE_PRIORITY = 10
SCORE_TIME_MULTIPLIER = 10**12


@dataclass
class QueueStatus:
    position: int
    queue_length: int
    priority: int
    queued_at: datetime | None
    blocked_reason: str | None = None


@dataclass
class DequeueResult:
    payload: dict[str, Any] | None
    all_blocked: bool = False


class PipelineAlreadyQueuedError(RuntimeError):
    """Le projet est déjà présent dans la file d'attente."""


def compute_queue_score(priority: int, enqueued_at_ms: int) -> float:
    clamped = max(0, min(priority, MAX_QUEUE_PRIORITY))
    return float((MAX_QUEUE_PRIORITY - clamped) * SCORE_TIME_MULTIPLIER + enqueued_at_ms)


def _payload_key(project_id: str) -> str:
    return f"{PIPELINE_PAYLOAD_PREFIX}{project_id}"


async def _resolve_queue_priority(user_id: uuid.UUID) -> int:
    async with AsyncSessionFactory() as session:
        user = await session.get(User, user_id)
        if user is None:
            return DEFAULT_QUEUE_PRIORITY
        limits = await resolve_user_limits(session, user)
        return limits.pipeline_queue_priority


async def _set_project_queued(
    project_id: uuid.UUID,
    *,
    priority: int,
    queued_at: datetime,
) -> None:
    async with AsyncSessionFactory() as session:
        project = await session.get(Project, project_id)
        if project is None:
            raise ValueError(f"Projet {project_id} introuvable")
        config = dict(project.config or {})
        config["queue_priority"] = priority
        config["queued_at"] = queued_at.isoformat()
        project.config = config
        project.status = "queued"
        project.error_message = None
        await session.commit()


async def _set_project_pending(project_id: uuid.UUID) -> None:
    async with AsyncSessionFactory() as session:
        project = await session.get(Project, project_id)
        if project is None:
            return
        config = dict(project.config or {})
        config.pop("queued_at", None)
        config.pop("queue_priority", None)
        config.pop("queue_blocked_reason", None)
        project.config = config
        project.status = "pending"
        project.error_message = None
        await session.commit()


async def _set_disk_wait_message(project_id: uuid.UUID, message: str) -> None:
    async with AsyncSessionFactory() as session:
        project = await session.get(Project, project_id)
        if project is None:
            return
        config = dict(project.config or {})
        config["queue_blocked_reason"] = "disk_space"
        project.config = config
        project.error_message = message
        await session.commit()


async def enqueue_pipeline_task(
    project_id: uuid.UUID,
    *,
    user_id: uuid.UUID | None = None,
    start_from: str | None = None,
    critic_feedback: list[dict[str, Any]] | None = None,
    critic_start_from: str | None = None,
    resume_iteration: int | None = None,
    reconcile_orphan: bool = False,
) -> QueueStatus:
    """Ajoute un pipeline à la file prioritaire."""
    project_key = str(project_id)
    await queue.connect()

    if await queue.client.zscore(PIPELINE_ZQUEUE, project_key) is not None:
        raise PipelineAlreadyQueuedError(f"Projet {project_id} déjà en file d'attente")

    async with AsyncSessionFactory() as session:
        project = await session.get(Project, project_id)
        if project is None:
            raise ValueError(f"Projet {project_id} introuvable")
        if project.status == "running":
            if reconcile_orphan:
                if await has_active_lease(project_id):
                    raise RuntimeError(
                        f"Pipeline encore actif pour le projet {project_id}"
                    )
            else:
                raise RuntimeError(f"Pipeline déjà en cours pour le projet {project_id}")
        channel = await session.get(Channel, project.channel_id)
        if channel is None:
            raise ValueError(f"Chaîne {project.channel_id} introuvable")
        resolved_user_id = user_id or channel.user_id

    if start_from is None and critic_start_from is None:
        plan = await resolve_start_from(project_id)
        start_from = plan.step
        if resume_iteration is None and plan.iteration > 1:
            resume_iteration = plan.iteration

    await queue.clear_pipeline_cancel(project_key)

    priority = await _resolve_queue_priority(resolved_user_id)
    queued_at = datetime.now(timezone.utc)
    enqueued_at_ms = int(queued_at.timestamp() * 1000)
    score = compute_queue_score(priority, enqueued_at_ms)

    payload: dict[str, Any] = {
        "project_id": project_key,
        "channel_id": str(channel.id),
        "user_id": str(resolved_user_id),
        "priority": priority,
        "score": score,
        "enqueued_at_ms": enqueued_at_ms,
        "queued_at": queued_at.isoformat(),
        "start_from": start_from,
        "critic_feedback": critic_feedback,
        "critic_start_from": critic_start_from,
        "resume_iteration": resume_iteration,
    }

    await queue.client.set(_payload_key(project_key), json.dumps(payload))
    await queue.client.zadd(PIPELINE_ZQUEUE, {project_key: score})
    await _set_project_queued(project_id, priority=priority, queued_at=queued_at)

    status = await get_queue_status(project_id)
    logger.info(
        "Pipeline enqueued projet=%s priorité=%d position=%d",
        project_id,
        priority,
        status.position,
    )
    return status


async def reenqueue_with_same_score(project_id: uuid.UUID, score: float) -> None:
    project_key = str(project_id)
    await queue.client.zadd(PIPELINE_ZQUEUE, {project_key: score})


async def remove_from_queue(project_id: uuid.UUID) -> bool:
    """Retire un projet de la file. Retourne False s'il n'y était pas."""
    project_key = str(project_id)
    await queue.connect()
    removed = await queue.client.zrem(PIPELINE_ZQUEUE, project_key)
    await queue.client.delete(_payload_key(project_key))
    if removed:
        await _set_project_pending(project_id)
        logger.info("Projet %s retiré de la file d'attente", project_id)
    return bool(removed)


async def is_queued(project_id: uuid.UUID) -> bool:
    await queue.connect()
    score = await queue.client.zscore(PIPELINE_ZQUEUE, str(project_id))
    return score is not None


async def get_queue_length() -> int:
    await queue.connect()
    return int(await queue.client.zcard(PIPELINE_ZQUEUE))


async def get_queue_position(project_id: uuid.UUID) -> int | None:
    await queue.connect()
    rank = await queue.client.zrank(PIPELINE_ZQUEUE, str(project_id))
    if rank is None:
        return None
    return int(rank) + 1


async def get_queue_status(project_id: uuid.UUID) -> QueueStatus:
    blocked_reason: str | None = None
    async with AsyncSessionFactory() as session:
        project = await session.get(Project, project_id)
        if project is None:
            raise ValueError(f"Projet {project_id} introuvable")
        config = project.config or {}
        if config.get("queue_blocked_reason") == "disk_space":
            blocked_reason = project.error_message

    position = await get_queue_position(project_id) or 0
    queue_length = await get_queue_length()
    priority = int(config.get("queue_priority", DEFAULT_QUEUE_PRIORITY))
    queued_at_raw = config.get("queued_at")
    queued_at = datetime.fromisoformat(queued_at_raw) if queued_at_raw else None

    return QueueStatus(
        position=position,
        queue_length=queue_length,
        priority=priority,
        queued_at=queued_at,
        blocked_reason=blocked_reason,
    )


async def get_queue_snapshot(
    *,
    limit: int = 50,
    user_id: uuid.UUID | None = None,
) -> list[dict[str, Any]]:
    await queue.connect()
    entries = await queue.client.zrange(PIPELINE_ZQUEUE, 0, limit - 1, withscores=True)
    if not entries:
        return []

    project_ids = [uuid.UUID(member) for member, _ in entries]
    async with AsyncSessionFactory() as session:
        result = await session.execute(
            select(Project, Channel)
            .join(Channel, Channel.id == Project.channel_id)
            .where(Project.id.in_(project_ids))
        )
        by_id = {p.id: (p, c) for p, c in result.all()}

    snapshot: list[dict[str, Any]] = []
    for index, (member, score) in enumerate(entries, start=1):
        pid = uuid.UUID(member)
        project_channel = by_id.get(pid)
        if project_channel is None:
            continue
        project, channel = project_channel
        if user_id is not None and channel.user_id != user_id:
            continue
        config = project.config or {}
        snapshot.append(
            {
                "position": index,
                "project_id": str(pid),
                "channel_id": str(project.channel_id),
                "channel_name": channel.name,
                "theme": project.theme,
                "title": project.title,
                "priority": int(config.get("queue_priority", DEFAULT_QUEUE_PRIORITY)),
                "queued_at": config.get("queued_at"),
                "score": score,
            }
        )
    return snapshot


async def prune_orphan_queue_entries() -> int:
    """Purge les entrées de file dont le projet n'existe plus ou n'est plus
    en état « queued ».

    Appelée au démarrage du worker et périodiquement (réconciliation) pour
    réparer la file : une suppression de projet ou un changement d'état hors
    file peut laisser un membre ZSET + payload orphelins, qui bloque alors la
    tête de file. Retourne le nombre d'entrées purgées.
    """
    await queue.connect()
    members = await queue.client.zrange(PIPELINE_ZQUEUE, 0, -1)
    if not members:
        return 0

    project_ids = [uuid.UUID(member) for member in members]
    async with AsyncSessionFactory() as session:
        result = await session.execute(
            select(Project.id, Project.status).where(Project.id.in_(project_ids))
        )
        status_by_id = {row.id: row.status for row in result.all()}

    pruned = 0
    for member in members:
        pid = uuid.UUID(member)
        status = status_by_id.get(pid)
        if status == "queued":
            continue
        await queue.client.zrem(PIPELINE_ZQUEUE, member)
        await queue.client.delete(_payload_key(member))
        pruned += 1
        logger.info(
            "Entrée orpheline purgée de la file projet=%s status=%s",
            pid,
            status,
        )
    if pruned:
        logger.info("Purge file d'attente : %d entrée(s) orpheline(s) retirée(s)", pruned)
    return pruned


async def _load_payload(project_id: str) -> dict[str, Any] | None:
    raw = await queue.client.get(_payload_key(project_id))
    if not raw:
        return None
    return json.loads(raw)


async def dequeue_next_eligible() -> DequeueResult:
    """Pop la prochaine tâche éligible (disque + slot chaîne)."""
    cfg = get_pipeline_settings()
    await queue.connect()

    attempts = 0
    blocked_count = 0

    while attempts < cfg.queue_dequeue_max_attempts:
        attempts += 1
        popped = await queue.client.zpopmin(PIPELINE_ZQUEUE, count=1)
        if not popped:
            return DequeueResult(payload=None, all_blocked=False)

        project_key, score = popped[0]
        project_id = uuid.UUID(project_key)
        payload = await _load_payload(project_key)
        if payload is None:
            logger.warning("Payload manquant pour projet %s — ignoré", project_key)
            continue

        # Entrée orpheline : projet supprimé ou plus en état « queued » → abandon
        # définitif. Ne JAMAIS ré-enfiler, sinon elle reste en tête de file (plus
        # petit score) et monopolise toutes les tentatives, bloquant les projets
        # légitimes derrière elle.
        async with AsyncSessionFactory() as session:
            project = await session.get(Project, project_id)
            project_status = project.status if project else None
        if project_status != "queued":
            await queue.client.delete(_payload_key(project_key))
            logger.warning(
                "Entrée orpheline retirée de la file projet=%s status=%s",
                project_id,
                project_status,
            )
            continue

        channel_id = uuid.UUID(payload["channel_id"])

        if not is_disk_sufficient():
            message = format_disk_wait_message()
            await _set_disk_wait_message(project_id, message)
            await reenqueue_with_same_score(project_id, float(score))
            blocked_count += 1
            continue

        claimed = await try_claim_project(project_id, channel_id)
        if not claimed:
            await reenqueue_with_same_score(project_id, float(score))
            blocked_count += 1
            continue

        async with AsyncSessionFactory() as session:
            project = await session.get(Project, project_id)
            if project:
                config = dict(project.config or {})
                config.pop("queue_blocked_reason", None)
                project.config = config
                project.error_message = None
                await session.commit()

        await queue.client.delete(_payload_key(project_key))
        logger.info("Projet %s claimé depuis la file (score=%s)", project_id, score)
        return DequeueResult(payload=payload, all_blocked=False)

    all_blocked = blocked_count > 0
    return DequeueResult(payload=None, all_blocked=all_blocked)


async def migrate_legacy_pipeline_queue() -> int:
    """Migre l'ancienne list Redis FIFO vers la ZSET prioritaire."""
    await queue.connect()
    migrated = 0
    while True:
        raw = await queue.client.lpop(LEGACY_PIPELINE_QUEUE)
        if raw is None:
            break
        payload = json.loads(raw)
        project_id = uuid.UUID(payload["project_id"])
        async with AsyncSessionFactory() as session:
            project = await session.get(Project, project_id)
            if project is None:
                continue
            channel = await session.get(Channel, project.channel_id)
            user_id = channel.user_id if channel else None
        if user_id is None:
            continue
        if await is_queued(project_id):
            continue
        await enqueue_pipeline_task(
            project_id,
            user_id=user_id,
            start_from=payload.get("start_from"),
            critic_feedback=payload.get("critic_feedback"),
            critic_start_from=payload.get("critic_start_from"),
            resume_iteration=payload.get("resume_iteration"),
        )
        migrated += 1
    if migrated:
        logger.info("Migration queue legacy : %d tâche(s) migrée(s)", migrated)
    return migrated
