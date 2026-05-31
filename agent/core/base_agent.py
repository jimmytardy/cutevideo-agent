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
from agent.core.llm_config import (
    compact_learning_context,
    resolve_max_tokens,
    resolve_model,
)
from agent.core.learning_context import load_channel_context

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
        model: str | None = None,
        max_tokens: int | None = None,
        system: str | None = None,
        cacheable_context: str | None = None,
    ) -> str:
        """Appel standardisé à Claude avec résolution modèle/tokens et prompt caching."""
        resolved_model = model or resolve_model(self.name)
        resolved_max_tokens = resolve_max_tokens(self.name, max_tokens)

        user_content: list[dict[str, Any]] = []
        if cacheable_context and cacheable_context.strip():
            user_content.append(
                {
                    "type": "text",
                    "text": cacheable_context.strip(),
                    "cache_control": {"type": "ephemeral"},
                }
            )
        user_content.append({"type": "text", "text": prompt})

        kwargs: dict[str, Any] = {
            "model": resolved_model,
            "max_tokens": resolved_max_tokens,
            "messages": [{"role": "user", "content": user_content}],
        }
        if system and system.strip():
            kwargs["system"] = [
                {
                    "type": "text",
                    "text": system.strip(),
                    "cache_control": {"type": "ephemeral"},
                }
            ]

        response = await self.claude.messages.create(**kwargs)
        return response.content[0].text

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
