from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass
from zoneinfo import ZoneInfo
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from agent.core.base_agent import stop_running_agent_runs
from agent.core.channel_config import ChannelRuntimeConfig, resolve_channel_config
from agent.core.concurrency import can_start_pipeline
from agent.core.subscription import (
    SubscriptionLimits,
    resolve_effective_max_critic_iterations,
    resolve_user_limits,
)
from agent.core.database import (
    AsyncSessionFactory,
    Channel,
    Project,
    User,
)
from agent.core.pipeline_cancel import is_worker_shutdown
from agent.core.studio_resume import INTERRUPTED_MESSAGE, LIMIT_MESSAGE, StudioPaused
from agent.core.queue import queue

logger = logging.getLogger(__name__)


async def _raise_if_cancelled(project_id: uuid.UUID) -> None:
    if await queue.is_pipeline_cancel_requested(str(project_id)):
        raise asyncio.CancelledError()


@dataclass
class PipelineContext:
    project_id: uuid.UUID
    channel_id: uuid.UUID
    user_id: uuid.UUID
    channel_slug: str
    theme_category: str
    niche_prompt: str
    channel_config: ChannelRuntimeConfig
    channel: Channel
    theme: str
    target_duration_seconds: int
    max_critic_iterations: int | None = None
    content_plan: dict[str, Any] | None = None
    # Remise en file après un worker interrompu : reprendre la création au lieu de repartir de zéro.
    resume: bool = False


class Orchestrator:
    """Lance la création Claude Studio d'un projet et met à jour son statut."""

    async def run_pipeline(
        self,
        project_id: uuid.UUID,
        *,
        already_claimed: bool = False,
        resume: bool = False,
    ) -> None:
        async with AsyncSessionFactory() as session:
            project = await self._get_project(session, project_id)
            if not project:
                raise ValueError(f"Projet {project_id} introuvable")

            channel = await self._get_channel(session, project.channel_id)
            if not channel:
                raise ValueError(f"Chaîne {project.channel_id} introuvable")

            if already_claimed:
                if project.status != "running":
                    raise RuntimeError(
                        f"Projet {project_id} non claimé (status={project.status})"
                    )
            else:
                if not await can_start_pipeline(project.channel_id):
                    raise RuntimeError(
                        f"Slot pipeline occupé pour la chaîne {channel.slug} "
                        f"(max {channel.max_concurrent_pipelines})"
                    )
                await self._update_project_status(session, project_id, "running")

        await _raise_if_cancelled(project_id)

        try:
            project_config = project.config or {}
            async with AsyncSessionFactory() as init_session:
                user = await init_session.get(User, channel.user_id)
                limits = (
                    await resolve_user_limits(init_session, user)
                    if user
                    else SubscriptionLimits()
                )
            channel_config = resolve_channel_config(channel, subscription_limits=limits)
            max_critic_iterations = resolve_effective_max_critic_iterations(
                project_config=project_config,
                channel_max=channel_config.max_critic_iterations,
                limits=limits,
            )
            ctx = PipelineContext(
                project_id=project_id,
                channel_id=channel.id,
                user_id=channel.user_id,
                channel_slug=channel.slug,
                theme_category=channel.theme_category,
                niche_prompt=channel.niche_prompt or "",
                channel_config=channel_config,
                channel=channel,
                theme=project.theme,
                # Shorts uniquement : durée du projet, sinon celle de la chaîne.
                target_duration_seconds=project.target_duration_seconds or channel_config.short_duration_s,
                max_critic_iterations=max_critic_iterations,
                content_plan=project_config.get("content_plan"),
                resume=resume,
            )

        except Exception as e:
            error_msg = f"{type(e).__name__}: {e}"
            async with AsyncSessionFactory() as session:
                await self._update_project_status(session, project_id, "failed", error_msg)
            logger.error("Pipeline init échoué pour le projet %s : %s", project_id, e)
            raise

        try:
            from agent.core.claude_studio import ClaudeStudioRunner
            from agent.core.storage import cleanup_local_videos_for_project

            await ClaudeStudioRunner(ctx).run()
            await cleanup_local_videos_for_project(project_id)

            async with AsyncSessionFactory() as session:
                await self._update_project_status(session, project_id, "approved")
            logger.info("Pipeline terminé pour le projet %s", project_id)
        except asyncio.CancelledError:
            from agent.core.storage import cleanup_local_videos_for_project
            from agent.core.subprocess_registry import kill_all

            await kill_all()
            if is_worker_shutdown() and not await queue.is_pipeline_cancel_requested(str(project_id)):
                # Redémarrage du worker : le projet reste `running` ; sans lease, le worker suivant le
                # remet en file (pipeline_reconcile) et la création reprend (studio_resume).
                async with AsyncSessionFactory() as session:
                    await self._update_project_status(session, project_id, "running", INTERRUPTED_MESSAGE)
                logger.info("Pipeline interrompu (arrêt du worker) pour le projet %s : reprise au redémarrage", project_id)
                raise
            await cleanup_local_videos_for_project(project_id)
            async with AsyncSessionFactory() as session:
                await self._update_project_status(session, project_id, "stopped", "Arrêté manuellement")
            await stop_running_agent_runs(project_id)
            logger.info("Pipeline annulé pour le projet %s", project_id)
            raise
        except StudioPaused as paused:
            # Limite d'usage de l'abonnement Claude : le worker reprendra la création après le reset.
            local = paused.until.astimezone(ZoneInfo("Europe/Paris"))
            async with AsyncSessionFactory() as session:
                await self._update_project_status(
                    session, project_id, "paused",
                    f"{LIMIT_MESSAGE} — reprise automatique le {local:%d/%m à %H:%M}",
                )
            logger.info("Pipeline en pause pour le projet %s jusqu'à %s", project_id, paused.until.isoformat())
        except Exception as e:
            error_msg = f"{type(e).__name__}: {e}"
            async with AsyncSessionFactory() as session:
                await self._update_project_status(session, project_id, "failed", error_msg)
            logger.error("Pipeline échoué pour le projet %s : %s", project_id, e)
            raise

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
