from __future__ import annotations

import json
import logging
from typing import Any

import redis.asyncio as aioredis
import redis.exceptions

from agent.core.config import settings

logger = logging.getLogger(__name__)

PIPELINE_QUEUE = "cutevideo:pipeline"
LEGACY_PIPELINE_QUEUE = PIPELINE_QUEUE
PIPELINE_ZQUEUE = "cutevideo:pipeline:zqueue"
PIPELINE_PAYLOAD_PREFIX = "cutevideo:pipeline:payload:"
AGENT_STATUS_PREFIX = "cutevideo:agent_status:"
PIPELINE_CANCEL_PREFIX = "cutevideo:pipeline_cancel:"
PIPELINE_LEASE_PREFIX = "cutevideo:pipeline:lease:"

# BLPOP timeout du worker (s) — le socket_timeout Redis doit rester au-dessus.
WORKER_BLPOP_TIMEOUT_S = 5
REDIS_SOCKET_TIMEOUT_S = 30


class AgentQueue:
    """Queue Redis pour la communication inter-agents."""

    def __init__(self) -> None:
        self._client: aioredis.Redis | None = None

    async def connect(self) -> None:
        if self._client is not None:
            await self.disconnect()
        self._client = aioredis.from_url(
            settings.redis_url,
            decode_responses=True,
            socket_connect_timeout=5,
            # Laisser BLPOP gérer l'attente ; un socket_timeout trop court provoque
            # redis.exceptions.TimeoutError au lieu d'un retour nil.
            socket_timeout=REDIS_SOCKET_TIMEOUT_S,
            retry_on_timeout=True,
            health_check_interval=30,
        )
        await self._client.ping()
        logger.info("Connexion Redis établie")

    async def disconnect(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    @property
    def client(self) -> aioredis.Redis:
        if not self._client:
            raise RuntimeError("Queue non connectée — appeler connect() d'abord")
        return self._client

    async def push_task(self, queue_name: str, payload: dict[str, Any]) -> None:
        """Pousse une tâche dans une queue Redis."""
        await self.client.rpush(queue_name, json.dumps(payload))
        logger.debug("Tâche poussée dans %s : %s", queue_name, payload)

    async def pop_task(self, queue_name: str, timeout: int = 0) -> dict[str, Any] | None:
        """Récupère la prochaine tâche (bloquant si timeout > 0)."""
        try:
            result = await self.client.blpop(queue_name, timeout=timeout)
        except redis.exceptions.TimeoutError:
            logger.debug("BLPOP timeout sur %s (queue vide)", queue_name)
            return None
        except redis.exceptions.ConnectionError as exc:
            logger.warning("Connexion Redis perdue pendant BLPOP : %s", exc)
            raise
        if result is None:
            return None
        _, raw = result
        return json.loads(raw)

    async def set_agent_status(self, project_id: str, agent_name: str, status: str) -> None:
        """Met à jour le statut d'un agent en temps réel."""
        key = f"{AGENT_STATUS_PREFIX}{project_id}:{agent_name}"
        await self.client.set(key, status, ex=3600)

    async def get_agent_status(self, project_id: str, agent_name: str) -> str | None:
        """Lit le statut d'un agent."""
        key = f"{AGENT_STATUS_PREFIX}{project_id}:{agent_name}"
        return await self.client.get(key)

    async def get_all_agent_statuses(self, project_id: str) -> dict[str, str]:
        """Lit tous les statuts agents d'un projet."""
        pattern = f"{AGENT_STATUS_PREFIX}{project_id}:*"
        keys = await self.client.keys(pattern)
        statuses: dict[str, str] = {}
        for key in keys:
            agent_name = key.split(":")[-1]
            value = await self.client.get(key)
            if value:
                statuses[agent_name] = value
        return statuses

    async def request_pipeline_cancel(self, project_id: str) -> None:
        """Signale au worker qu'un pipeline doit s'arrêter coopérativement."""
        key = f"{PIPELINE_CANCEL_PREFIX}{project_id}"
        await self.client.set(key, "1", ex=3600)

    async def clear_pipeline_cancel(self, project_id: str) -> None:
        key = f"{PIPELINE_CANCEL_PREFIX}{project_id}"
        await self.client.delete(key)

    async def is_pipeline_cancel_requested(self, project_id: str) -> bool:
        key = f"{PIPELINE_CANCEL_PREFIX}{project_id}"
        return await self.client.exists(key) > 0

    async def clear_agent_statuses(
        self, project_id: str, agent_names: list[str] | None = None
    ) -> None:
        """Supprime les statuts Redis d'un projet (tous ou une liste d'agents)."""
        if agent_names is None:
            pattern = f"{AGENT_STATUS_PREFIX}{project_id}:*"
            keys = await self.client.keys(pattern)
        else:
            keys = [f"{AGENT_STATUS_PREFIX}{project_id}:{name}" for name in agent_names]
        if keys:
            await self.client.delete(*keys)


queue = AgentQueue()
