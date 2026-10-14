from __future__ import annotations

import logging

import redis.asyncio as aioredis
import redis.exceptions

from agent.core.config import settings

logger = logging.getLogger(__name__)

PIPELINE_QUEUE = "cutevideo:pipeline"
PIPELINE_ZQUEUE = "cutevideo:pipeline:zqueue"
PIPELINE_PAYLOAD_PREFIX = "cutevideo:pipeline:payload:"
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
        # Connexion paresseuse réutilisable : on ne (re)connecte que si le client
        # n'existe pas. Le client redis.asyncio gère lui-même la reconnexion via
        # health_check_interval / retry_on_timeout, donc inutile de tout reconstruire
        # à chaque appel (sinon une nouvelle connexion par opération, plusieurs/s).
        if self._client is not None:
            return

        import asyncio

        last_error: Exception | None = None
        for attempt in range(1, 11):
            client: aioredis.Redis | None = None
            try:
                client = aioredis.from_url(
                    settings.redis_url,
                    decode_responses=True,
                    socket_connect_timeout=5,
                    socket_timeout=REDIS_SOCKET_TIMEOUT_S,
                    retry_on_timeout=True,
                    health_check_interval=30,
                )
                await client.ping()
                self._client = client
                logger.info("Connexion Redis établie")
                return
            except (redis.exceptions.ConnectionError, OSError) as exc:
                last_error = exc
                if client is not None:
                    await client.aclose()
                if attempt < 10:
                    delay = min(attempt, 3)
                    logger.warning(
                        "Redis indisponible (tentative %d/10) : %s — nouvel essai dans %ds",
                        attempt,
                        exc,
                        delay,
                    )
                    await asyncio.sleep(delay)

        assert last_error is not None
        raise last_error

    async def disconnect(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    @property
    def client(self) -> aioredis.Redis:
        if not self._client:
            raise RuntimeError("Queue non connectée — appeler connect() d'abord")
        return self._client


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


queue = AgentQueue()
