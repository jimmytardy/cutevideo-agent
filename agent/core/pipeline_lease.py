from __future__ import annotations

import logging
import uuid

from agent.core.config import load_agent_config
from agent.core.queue import PIPELINE_LEASE_PREFIX, queue

logger = logging.getLogger(__name__)


def _lease_key(project_id: uuid.UUID | str) -> str:
    return f"{PIPELINE_LEASE_PREFIX}{project_id}"


def get_lease_settings() -> tuple[int, int]:
    """Retourne (ttl_seconds, renew_interval_seconds)."""
    cfg = load_agent_config().get("pipeline", {})
    ttl = int(cfg.get("lease_ttl_seconds", 60))
    renew = int(cfg.get("lease_renew_interval_seconds", max(ttl // 2, 1)))
    return ttl, renew


async def acquire_lease(project_id: uuid.UUID, worker_id: str) -> None:
    """Prend un lease Redis pour signaler qu'un worker exécute ce pipeline."""
    await queue.connect()
    ttl, _ = get_lease_settings()
    key = _lease_key(project_id)
    await queue.client.set(key, worker_id, ex=ttl)
    logger.debug("Lease acquis projet=%s worker=%s ttl=%ds", project_id, worker_id, ttl)


async def renew_lease(project_id: uuid.UUID, worker_id: str) -> bool:
    """Renouvelle le lease si le worker en est toujours propriétaire."""
    await queue.connect()
    ttl, _ = get_lease_settings()
    key = _lease_key(project_id)
    current = await queue.client.get(key)
    if current != worker_id:
        return False
    await queue.client.expire(key, ttl)
    return True


async def release_lease(project_id: uuid.UUID, worker_id: str | None = None) -> None:
    """Libère le lease (best-effort, vérifie le propriétaire si worker_id fourni)."""
    await queue.connect()
    key = _lease_key(project_id)
    if worker_id is not None:
        current = await queue.client.get(key)
        if current != worker_id:
            return
    await queue.client.delete(key)
    logger.debug("Lease libéré projet=%s", project_id)


async def has_active_lease(project_id: uuid.UUID) -> bool:
    """True si un worker actif détient un lease pour ce projet."""
    await queue.connect()
    key = _lease_key(project_id)
    return await queue.client.exists(key) > 0
