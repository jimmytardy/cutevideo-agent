from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from agent.core.channel_config import ChannelRuntimeConfig, resolve_channel_config
from agent.core.learning_context import ChannelContextSnapshot, load_channel_context
from agent.core.concurrency import can_start_pipeline
from agent.core.database import (
    AsyncSessionFactory,
    Channel,
    CriticReport,
    Project,
    Scenario,
    Video,
)
from agent.core.config import settings
from agent.core.queue import queue

logger = logging.getLogger(__name__)

AGENT_ORDER = [
    "scenario_agent",
    "media_agent",
    "narrator_agent",
    "editor_agent",
    "subtitle_agent",
    "critic_agent",
    "clipper_agent",
    "short_editor_agent",
]

ENGAGEMENT_AGENT_ORDER = [
    "analytics_agent",
    "comments_agent",
]


@dataclass
class PipelineContext:
    project_id: uuid.UUID
    channel_id: uuid.UUID
    channel_slug: str
    theme_category: str
    niche_prompt: str
    channel_config: ChannelRuntimeConfig
    channel: Channel
    theme: str
    target_duration_seconds: int
    iteration: int = 1
    learning_context: ChannelContextSnapshot | None = None
    content_plan: dict[str, Any] | None = None
    planned_shorts: list[dict[str, Any]] | None = None

    @property
    def learning_context_prompt(self) -> str:
        if self.learning_context:
            return self.learning_context.format_for_prompt()
        return "Aucun retour audience ou analytics enregistré pour cette chaîne."


class Orchestrator:
    """Lance et supervise le pipeline multi-agents."""

    async def run_pipeline(self, project_id: uuid.UUID) -> None:
        """Exécute le pipeline complet pour un projet."""
        async with AsyncSessionFactory() as session:
            project = await self._get_project(session, project_id)
            if not project:
                raise ValueError(f"Projet {project_id} introuvable")

            channel = await self._get_channel(session, project.channel_id)
            if not channel:
                raise ValueError(f"Chaîne {project.channel_id} introuvable")

            if not await can_start_pipeline(project.channel_id):
                raise RuntimeError(
                    f"Slot pipeline occupé pour la chaîne {channel.slug} "
                    f"(max {channel.max_concurrent_pipelines})"
                )

            await self._update_project_status(session, project_id, "running")

        learning = await load_channel_context(channel.id)
        project_config = project.config or {}
        ctx = PipelineContext(
            project_id=project_id,
            channel_id=channel.id,
            channel_slug=channel.slug,
            theme_category=channel.theme_category,
            niche_prompt=channel.niche_prompt or "",
            channel_config=resolve_channel_config(channel),
            channel=channel,
            theme=project.theme,
            target_duration_seconds=project.target_duration_seconds or 1800,
            learning_context=learning,
            content_plan=project_config.get("content_plan"),
            planned_shorts=project_config.get("planned_shorts"),
        )
        logger.info(
            "Contexte apprentissage chaîne %s (v%d) chargé pour le projet %s",
            channel.slug,
            learning.version,
            project_id,
        )

        try:
            await self._run_creation_pipeline(ctx)
            await self._run_shorts_pipeline(ctx)
            async with AsyncSessionFactory() as session:
                await self._update_project_status(session, project_id, "approved")
            logger.info("Pipeline terminé pour le projet %s (chaîne %s)", project_id, channel.slug)
        except Exception as e:
            async with AsyncSessionFactory() as session:
                await self._update_project_status(session, project_id, "failed")
            logger.error("Pipeline échoué pour le projet %s : %s", project_id, e)
            raise

    async def _run_creation_pipeline(self, ctx: PipelineContext) -> None:
        """Étapes 1-6 : scénario → montage → critique avec itérations."""
        from agent.agents.scenario_agent import ScenarioAgent
        from agent.agents.media_agent import MediaAgent
        from agent.agents.narrator_agent import NarratorAgent
        from agent.agents.editor_agent import EditorAgent
        from agent.agents.subtitle_agent import SubtitleAgent
        from agent.agents.critic_agent import CriticAgent

        await queue.set_agent_status(str(ctx.project_id), "scenario_agent", "running")
        scenario = await ScenarioAgent().run(ctx)
        await queue.set_agent_status(str(ctx.project_id), "scenario_agent", "success")

        max_iterations = ctx.channel_config.max_critic_iterations
        for iteration in range(1, max_iterations + 1):
            ctx.iteration = iteration

            await queue.set_agent_status(str(ctx.project_id), "media_agent", "running")
            await MediaAgent().run(ctx, scenario)
            await queue.set_agent_status(str(ctx.project_id), "media_agent", "success")

            await queue.set_agent_status(str(ctx.project_id), "narrator_agent", "running")
            await NarratorAgent().run(ctx, scenario)
            await queue.set_agent_status(str(ctx.project_id), "narrator_agent", "success")

            await queue.set_agent_status(str(ctx.project_id), "editor_agent", "running")
            video = await EditorAgent().run(ctx)
            await queue.set_agent_status(str(ctx.project_id), "editor_agent", "success")

            await queue.set_agent_status(str(ctx.project_id), "subtitle_agent", "running")
            await SubtitleAgent().run(ctx, video)
            await queue.set_agent_status(str(ctx.project_id), "subtitle_agent", "success")

            await queue.set_agent_status(str(ctx.project_id), "critic_agent", "running")
            report = await CriticAgent().run(ctx, video, scenario, iteration)
            await queue.set_agent_status(str(ctx.project_id), "critic_agent", "success")

            if report.decision == "approve":
                logger.info(
                    "Critique approuve à l'itération %d (score %d/100) — chaîne %s",
                    iteration,
                    report.global_score,
                    ctx.channel_slug,
                )
                break

            logger.info(
                "Critique demande une itération %d → %d (score %d/100)",
                iteration,
                iteration + 1,
                report.global_score,
            )
            await self._apply_critic_changes(ctx, report, scenario)

    async def _run_shorts_pipeline(self, ctx: PipelineContext) -> None:
        """Étapes 7-8 : découpage + édition des shorts."""
        from agent.agents.clipper_agent import ClipperAgent
        from agent.agents.short_editor_agent import ShortEditorAgent

        await queue.set_agent_status(str(ctx.project_id), "clipper_agent", "running")
        clips = await ClipperAgent().run(ctx)
        await queue.set_agent_status(str(ctx.project_id), "clipper_agent", "success")

        await queue.set_agent_status(str(ctx.project_id), "short_editor_agent", "running")
        await ShortEditorAgent().run(ctx, clips)
        await queue.set_agent_status(str(ctx.project_id), "short_editor_agent", "success")

    async def _apply_critic_changes(
        self,
        ctx: PipelineContext,
        report: CriticReport,
        scenario: Scenario,
    ) -> None:
        """Applique les changements demandés par le critique."""
        if not report.requested_changes:
            return
        for change in report.requested_changes:
            agent_name = change.get("agent", "")
            logger.info("Changement demandé pour %s : %s", agent_name, change.get("change_description"))

    @staticmethod
    async def _get_project(session: AsyncSession, project_id: uuid.UUID) -> Project | None:
        result = await session.execute(select(Project).where(Project.id == project_id))
        return result.scalar_one_or_none()

    @staticmethod
    async def _get_channel(session: AsyncSession, channel_id: uuid.UUID) -> Channel | None:
        result = await session.execute(select(Channel).where(Channel.id == channel_id))
        return result.scalar_one_or_none()

    @staticmethod
    async def _update_project_status(session: AsyncSession, project_id: uuid.UUID, status: str) -> None:
        await session.execute(
            update(Project).where(Project.id == project_id).values(status=status)
        )
        await session.commit()
