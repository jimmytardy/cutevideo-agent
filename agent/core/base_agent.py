from __future__ import annotations

import logging
import uuid
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Generic, TypeVar

import anthropic
from sqlalchemy.ext.asyncio import AsyncSession

from agent.core.config import settings
from agent.core.database import AgentRun, AsyncSessionFactory

logger = logging.getLogger(__name__)

InputT = TypeVar("InputT")
OutputT = TypeVar("OutputT")


class BaseAgent(ABC, Generic[InputT, OutputT]):
    """Classe de base pour tous les agents spécialisés."""

    name: str = "base_agent"

    def __init__(self) -> None:
        self.claude = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
        self._logger = logging.getLogger(f"agent.{self.name}")

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

    async def _call_claude(
        self,
        prompt: str,
        model: str = "claude-opus-4-5",
        max_tokens: int = 4096,
        system: str | None = None,
    ) -> str:
        """Appel standardisé à Claude."""
        messages = [{"role": "user", "content": prompt}]
        kwargs: dict[str, Any] = {
            "model": model,
            "max_tokens": max_tokens,
            "messages": messages,
        }
        if system:
            kwargs["system"] = system
        response = await self.claude.messages.create(**kwargs)
        return response.content[0].text

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
