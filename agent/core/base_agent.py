from __future__ import annotations

import logging
import uuid
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Generic, TypeVar

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agent.core.database import AgentRun, AsyncSessionFactory, User
from agent.core.llm_config import compact_learning_context, resolve_max_tokens
from agent.core.llm_resolver import call_llm
from agent.core.learning_context import load_channel_context

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

        now = datetime.now(timezone.utc)
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
    """Classe de base pour tous les agents spécialisés."""

    name: str = "base_agent"

    def __init__(self) -> None:
        self._logger = logging.getLogger(f"agent.{self.name}")
        self._user_id: uuid.UUID | None = None

    def bind_user(self, user_id: uuid.UUID | None) -> None:
        self._user_id = user_id

    @abstractmethod
    async def run(self, input_data: InputT) -> OutputT:
        """Point d'entrée principal de l'agent."""
        ...

    async def start_run(self, project_id: uuid.UUID, input_data: Any, iteration: int = 1) -> AgentRun:
        """Enregistre le début d'un run en DB."""
        async with AsyncSessionFactory() as session:
            run = AgentRun(
                project_id=project_id,
                agent_name=self.name,
                status="running",
                iteration=iteration,
                input_json=self._serialize(input_data),
                started_at=datetime.now(timezone.utc),
            )
            session.add(run)
            await session.commit()
            await session.refresh(run)
            self._logger.info("Agent %s démarré — run %s", self.name, run.id)
            return run

    async def end_run(self, run: AgentRun, output_data: Any) -> None:
        """Enregistre la fin réussie d'un run en DB."""
        async with AsyncSessionFactory() as session:
            run.status = "success"
            run.output_json = self._serialize(output_data)
            run.ended_at = datetime.now(timezone.utc)
            session.add(run)
            await session.commit()
            self._logger.info("Agent %s terminé avec succès — run %s", self.name, run.id)

    async def fail_run(self, run: AgentRun, error: Exception) -> None:
        """Enregistre l'échec d'un run en DB."""
        async with AsyncSessionFactory() as session:
            run.status = "failed"
            run.error = str(error)
            run.ended_at = datetime.now(timezone.utc)
            session.add(run)
            await session.commit()
            self._logger.error("Agent %s échoué — run %s : %s", self.name, run.id, error)

    async def stop_run(self, run: AgentRun, reason: str = _STOPPED_BY_USER) -> None:
        """Enregistre l'arrêt manuel d'un run en DB."""
        async with AsyncSessionFactory() as session:
            run.status = "stopped"
            run.error = reason
            run.ended_at = datetime.now(timezone.utc)
            session.add(run)
            await session.commit()
            self._logger.info("Agent %s arrêté — run %s", self.name, run.id)

    async def _call_claude(
        self,
        prompt: str,
        model: str | None = None,
        max_tokens: int | None = None,
        system: str | None = None,
        cacheable_context: str | None = None,
    ) -> str:
        """Appel LLM (Gemini par défaut, Anthropic si configuré) via llm_resolver."""
        async with AsyncSessionFactory() as session:
            user: User | None = None
            if self._user_id is not None:
                user = await session.get(User, self._user_id)
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

    async def _call_claude_for_channel(
        self,
        channel_id: uuid.UUID,
        prompt: str,
        system: str | None = None,
        *,
        model: str | None = None,
        max_tokens: int | None = None,
        extra_cacheable: str | None = None,
    ) -> str:
        """Appel Claude avec contexte d'apprentissage chaîne en bloc cacheable."""
        snapshot = await load_channel_context(channel_id)
        context_block = compact_learning_context(snapshot)
        if extra_cacheable:
            context_block = f"{extra_cacheable.strip()}\n\n{context_block}"
        return await self._call_claude(
            prompt,
            model=model,
            max_tokens=max_tokens,
            system=system,
            cacheable_context=context_block,
        )

    @staticmethod
    def _serialize(data: Any) -> dict | None:
        """Sérialise un objet en dict pour stockage JSONB."""
        if data is None:
            return None
        if isinstance(data, dict):
            return data
        if hasattr(data, "__dict__"):
            return {k: str(v) for k, v in vars(data).items()}
        if hasattr(data, "__dataclass_fields__"):
            return asdict(data)  # type: ignore[arg-type]
        return {"value": str(data)}
