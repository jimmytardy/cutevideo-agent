from __future__ import annotations

import logging
import uuid
from abc import ABC, abstractmethod
from datetime import datetime, UTC
from typing import Generic, TypeVar

from sqlalchemy import select

from agent.core.database import AgentRun, AsyncSessionFactory, Channel, User
from agent.core.llm_resolver import call_llm

logger = logging.getLogger(__name__)

_STOPPED_BY_USER = "Arrêté manuellement"


async def stop_running_agent_runs(
    project_id: uuid.UUID,
    *,
    agent_name: str | None = None,
    reason: str = _STOPPED_BY_USER,
) -> int:
    """Marque les AgentRun encore en ``running`` comme ``stopped`` (annulation pipeline)."""
    async with AsyncSessionFactory() as session:
        query = select(AgentRun).where(
            AgentRun.project_id == project_id,
            AgentRun.status == "running",
        )
        if agent_name is not None:
            query = query.where(AgentRun.agent_name == agent_name)
        result = await session.execute(query)
        runs = list(result.scalars().all())
        if not runs:
            return 0

        now = datetime.now(UTC)
        for run in runs:
            run.status = "stopped"
            run.error = reason
            run.ended_at = now
            session.add(run)
        await session.commit()

        for run in runs:
            logger.info(
                "AgentRun %s (%s) marqué stopped — projet %s",
                run.id,
                run.agent_name,
                project_id,
            )
        return len(runs)


InputT = TypeVar("InputT")
OutputT = TypeVar("OutputT")


class BaseAgent(ABC, Generic[InputT, OutputT]):
    """Base des agents Python restants (planner, distribution) : nom, logger, appel LLM."""

    name: str = "base_agent"

    def __init__(self) -> None:
        self._logger = logging.getLogger(f"agent.{self.name}")

    @abstractmethod
    async def run(self, input_data: InputT) -> OutputT:
        """Point d'entrée principal de l'agent."""
        ...

    async def _call_llm_for_channel(
        self,
        channel_id: uuid.UUID,
        prompt: str,
        system: str | None = None,
        *,
        model: str | None = None,
        max_tokens: int | None = None,
        cacheable_context: str | None = None,
    ) -> str:
        """Appel LLM (Gemini, Anthropic ou Claude CLI via llm_resolver) avec les clés
        et préférences du propriétaire de la chaîne."""
        async with AsyncSessionFactory() as session:
            channel = await session.get(Channel, channel_id)
            user = await session.get(User, channel.user_id) if channel and channel.user_id else None
            return await call_llm(
                session,
                user,
                self.name,
                prompt,
                system=system,
                max_tokens=max_tokens,
                cacheable_context=cacheable_context,
                model_override=model,
            )
