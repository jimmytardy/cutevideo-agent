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

        try:
            learning = await load_channel_context(channel.id)
            project_config = project.config or {}
            channel_config = resolve_channel_config(channel)
            ctx = PipelineContext(
                project_id=project_id,
                channel_id=channel.id,
                channel_slug=channel.slug,
                theme_category=channel.theme_category,
                niche_prompt=channel.niche_prompt or "",
                channel_config=channel_config,
                channel=channel,
                theme=project.theme,
                target_duration_seconds=project.target_duration_seconds or 1800,
                learning_context=learning,
                content_plan=project_config.get("content_plan"),
                planned_shorts=project_config.get("planned_shorts"),
            )

        except Exception as e:
            error_msg = f"{type(e).__name__}: {e}"
            async with AsyncSessionFactory() as session:
                await self._update_project_status(session, project_id, "failed", error_msg)
            logger.error("Pipeline init échoué pour le projet %s : %s", project_id, e)
            raise

        try:
            is_short_project = project_config.get("format") in ("short_standalone", "short")
            if channel_config.production_mode == "shorts_only" or is_short_project:
                await self._run_shorts_only_pipeline(ctx)
            else:
                await self._run_creation_pipeline(ctx)
                if channel_config.production_mode != "long_only":
                    await self._run_shorts_pipeline(ctx)

            async with AsyncSessionFactory() as session:
                await self._update_project_status(session, project_id, "approved")
            logger.info("Pipeline terminé pour le projet %s", project_id)
        except Exception as e:
            error_msg = f"{type(e).__name__}: {e}"
            async with AsyncSessionFactory() as session:
                await self._update_project_status(session, project_id, "failed", error_msg)
            logger.error("Pipeline échoué pour le projet %s : %s", project_id, e)
            raise

    async def _run_creation_pipeline(self, ctx: PipelineContext) -> None:
        from agent.agents.scenario_agent import ScenarioAgent
        from agent.agents.media_agent import MediaAgent
        from agent.agents.narrator_agent import NarratorAgent
        from agent.agents.editor_agent import EditorAgent
        from agent.agents.subtitle_agent import SubtitleAgent
        from agent.agents.critic_agent import CriticAgent

        pid = str(ctx.project_id)
        current_agent = "scenario_agent"
        try:
            await queue.set_agent_status(pid, current_agent, "running")
            scenario = await ScenarioAgent().run(ctx)
            await queue.set_agent_status(pid, current_agent, "success")

            max_iterations = ctx.channel_config.max_critic_iterations
            video = None
            for iteration in range(1, max_iterations + 1):
                ctx.iteration = iteration

                current_agent = "media_agent"
                await queue.set_agent_status(pid, current_agent, "running")
                await MediaAgent().run(ctx, scenario)
                await queue.set_agent_status(pid, current_agent, "success")

                current_agent = "narrator_agent"
                await queue.set_agent_status(pid, current_agent, "running")
                await NarratorAgent().run(ctx, scenario)
                await queue.set_agent_status(pid, current_agent, "success")

                current_agent = "editor_agent"
                await queue.set_agent_status(pid, current_agent, "running")
                video = await EditorAgent().run(ctx, scenario)
                await queue.set_agent_status(pid, current_agent, "success")

                current_agent = "subtitle_agent"
                await queue.set_agent_status(pid, current_agent, "running")
                await SubtitleAgent().run(ctx, video)
                await queue.set_agent_status(pid, current_agent, "success")

                current_agent = "critic_agent"
                await queue.set_agent_status(pid, current_agent, "running")
                report = await CriticAgent().run(ctx, video, scenario, iteration)
                await queue.set_agent_status(pid, current_agent, "success")

                if report.decision == "approve":
                    break
                await self._apply_critic_changes(ctx, report, scenario)

        except Exception:
            await queue.set_agent_status(pid, current_agent, "failed")
            raise

    async def _run_shorts_only_pipeline(self, ctx: PipelineContext) -> None:
        from agent.agents.scenario_agent import ScenarioAgent
        from agent.agents.media_agent import MediaAgent
        from agent.agents.narrator_agent import NarratorAgent
        from agent.agents.editor_agent import EditorAgent
        from agent.agents.subtitle_agent import SubtitleAgent
        from agent.agents.critic_agent import CriticAgent
        from agent.agents.short_editor_agent import ShortEditorAgent

        pid = str(ctx.project_id)
        current_agent = "scenario_agent"
        try:
            await queue.set_agent_status(pid, current_agent, "running")
            scenario = await ScenarioAgent().run(ctx)
            await queue.set_agent_status(pid, current_agent, "success")

            max_iterations = min(ctx.channel_config.max_critic_iterations, 2)
            for iteration in range(1, max_iterations + 1):
                ctx.iteration = iteration

                current_agent = "media_agent"
                await queue.set_agent_status(pid, current_agent, "running")
                await MediaAgent().run(ctx, scenario)
                await queue.set_agent_status(pid, current_agent, "success")

                current_agent = "narrator_agent"
                await queue.set_agent_status(pid, current_agent, "running")
                await NarratorAgent().run(ctx, scenario)
                await queue.set_agent_status(pid, current_agent, "success")

                current_agent = "editor_agent"
                await queue.set_agent_status(pid, current_agent, "running")
                video = await EditorAgent().run(ctx, scenario)
                await queue.set_agent_status(pid, current_agent, "success")

                current_agent = "subtitle_agent"
                await queue.set_agent_status(pid, current_agent, "running")
                await SubtitleAgent().run(ctx, video)
                await queue.set_agent_status(pid, current_agent, "success")

                current_agent = "critic_agent"
                await queue.set_agent_status(pid, current_agent, "running")
                report = await CriticAgent().run(ctx, video, scenario, iteration)
                await queue.set_agent_status(pid, current_agent, "success")

                if report.decision == "approve":
                    break

            current_agent = "short_editor_agent"
            await queue.set_agent_status(pid, current_agent, "running")
            await ShortEditorAgent().run_platform_exports(ctx)
            await queue.set_agent_status(pid, current_agent, "success")

        except Exception:
            await queue.set_agent_status(pid, current_agent, "failed")
            raise

    async def _run_shorts_pipeline(self, ctx: PipelineContext) -> None:
        from agent.agents.clipper_agent import ClipperAgent
        from agent.agents.short_editor_agent import ShortEditorAgent

        pid = str(ctx.project_id)
        current_agent = "clipper_agent"
        try:
            await queue.set_agent_status(pid, current_agent, "running")
            clips = await ClipperAgent().run(ctx)
            await queue.set_agent_status(pid, current_agent, "success")

            current_agent = "short_editor_agent"
            await queue.set_agent_status(pid, current_agent, "running")
            await ShortEditorAgent().run(ctx, clips)
            await queue.set_agent_status(pid, current_agent, "success")

        except Exception:
            await queue.set_agent_status(pid, current_agent, "failed")
            raise

    async def _apply_critic_changes(
        self,
        ctx: PipelineContext,
        report: CriticReport,
        scenario: Scenario,
    ) -> None:
        if not report.requested_changes:
            return
        for change in report.requested_changes:
            logger.info("Changement demandé pour %s : %s", change.get("agent"), change.get("change_description"))

    @staticmethod
    async def _get_project(session: AsyncSession, project_id: uuid.UUID) -> Project | None:
        result = await session.execute(select(Project).where(Project.id == project_id))
        return result.scalar_one_or_none()

    @staticmethod
    async def _get_channel(session: AsyncSession, channel_id: uuid.UUID) -> Channel | None:
        result = await session.execute(select(Channel).where(Channel.id == channel_id))
        return result.scalar_one_or_none()

    @staticmethod
    async def _update_project_status(
        session: AsyncSession, project_id: uuid.UUID, status: str, error_message: str | None = None
    ) -> None:
        values: dict = {"status": status}
        if error_message is not None:
            values["error_message"] = error_message[:2000]
        await session.execute(update(Project).where(Project.id == project_id).values(**values))
        await session.commit()
