from __future__ import annotations

import json
import logging
from typing import Any

import redis.asyncio as aioredis

from agent.core.config import settings

logger = logging.getLogger(__name__)

PIPELINE_QUEUE = "cutevideo:pipeline"
AGENT_STATUS_PREFIX = "cutevideo:agent_status:"


class AgentQueue:
    """Queue Redis pour la communication inter-agents."""

    def __init__(self) -> None:
        self._client: aioredis.Redis | None = None

    async def connect(self) -> None:
        self._client = await aioredis.from_url(settings.redis_url, decode_responses=True)
        logger.info("Connexion Redis établie")

    async def disconnect(self) -> None:
        if self._client:
            await self._client.aclose()

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
        result = await self.client.blpop(queue_name, timeout=timeout)
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


queue = AgentQueue()
