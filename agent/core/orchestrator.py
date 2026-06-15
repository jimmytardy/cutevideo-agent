from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from agent.core.channel_config import ChannelRuntimeConfig, resolve_channel_config
from agent.core.learning_context import ChannelContextSnapshot, load_channel_context
from agent.core.concurrency import can_start_pipeline
from agent.core.database import (
    AsyncSessionFactory,
    AudioFile,
    Channel,
    CriticReport,
    MediaAsset,
    Project,
    Scenario,
    Video,
)
from agent.core.config import settings
from agent.core.queue import queue

logger = logging.getLogger(__name__)


async def _raise_if_cancelled(project_id: uuid.UUID) -> None:
    if await queue.is_pipeline_cancel_requested(str(project_id)):
        raise asyncio.CancelledError()


AGENT_ORDER = [
    "research_agent",
    "scenario_agent",
    "revision_agent",
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
    max_iterations_override: int | None = None
    learning_context: ChannelContextSnapshot | None = None
    content_plan: dict[str, Any] | None = None
    planned_shorts: list[dict[str, Any]] | None = None
    critic_feedback: list[dict] | None = None
    critic_start_from: str | None = None
    research_brief: dict[str, Any] | None = None
    derivation_short_index: int | None = None
    short_derivation_mode: Literal["reuse_pool_only", "free_sources_only", "full"] | None = None

    @property
    def learning_context_prompt(self) -> str:
        if self.learning_context:
            return self.learning_context.format_for_prompt()
        return "Aucun retour audience ou analytics enregistré pour cette chaîne."

    @property
    def is_short_project(self) -> bool:
        project_format = (self.content_plan or {}).get("format")
        if project_format in ("short_standalone", "short"):
            return True
        if self.channel_config.production_mode == "shorts_only":
            return True
        return self.target_duration_seconds <= 120


class Orchestrator:
    """Lance et supervise le pipeline multi-agents."""

    _SHORTS_STEPS = frozenset({"clipper_agent", "short_editor_agent"})

    async def run_pipeline(
        self,
        project_id: uuid.UUID,
        start_from: str | None = None,
        critic_feedback: list[dict] | None = None,
        critic_start_from: str | None = None,
    ) -> None:
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

        await _raise_if_cancelled(project_id)

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
                target_duration_seconds=project.target_duration_seconds or (
                    channel_config.short_duration_s
                    if channel_config.production_mode == "shorts_only"
                    else 1800
                ),
                max_iterations_override=project_config.get("max_critic_iterations"),
                learning_context=learning,
                content_plan=project_config.get("content_plan"),
                planned_shorts=project_config.get("planned_shorts"),
                critic_feedback=critic_feedback,
                critic_start_from=critic_start_from,
                research_brief=project_config.get("research_brief"),
            )

        except Exception as e:
            error_msg = f"{type(e).__name__}: {e}"
            async with AsyncSessionFactory() as session:
                await self._update_project_status(session, project_id, "failed", error_msg)
            logger.error("Pipeline init échoué pour le projet %s : %s", project_id, e)
            raise

        try:
            is_short_project = project_config.get("format") in ("short_standalone", "short")
            if start_from in self._SHORTS_STEPS:
                # Skip creation pipeline — jump straight to shorts
                await self._run_shorts_pipeline(ctx, start_from=start_from)
            elif channel_config.production_mode == "shorts_only" or is_short_project:
                await self._run_shorts_only_pipeline(ctx, start_from=start_from)
                await self._run_platform_exports(ctx)
            else:
                await self._run_creation_pipeline(ctx, start_from=start_from)
                if channel_config.production_mode != "long_only":
                    strategy = channel_config.short_derivation.strategy
                    if strategy == "crop":
                        await self._run_shorts_pipeline(ctx)
                    elif strategy == "native":
                        await self._run_native_shorts_pipeline(ctx)
                    else:
                        await self._run_native_shorts_pipeline(ctx, planned_only=True)
                        await self._run_shorts_pipeline(ctx, teaser_only=True)

            from agent.core.storage import cleanup_local_videos_for_project, cleanup_temp_ai_images

            await cleanup_local_videos_for_project(project_id)
            await cleanup_temp_ai_images(project_id)

            async with AsyncSessionFactory() as session:
                await self._update_project_status(session, project_id, "approved")
            logger.info("Pipeline terminé pour le projet %s", project_id)
        except asyncio.CancelledError:
            async with AsyncSessionFactory() as session:
                await self._update_project_status(session, project_id, "stopped", "Arrêté manuellement")
            logger.info("Pipeline annulé pour le projet %s", project_id)
            raise
        except Exception as e:
            error_msg = f"{type(e).__name__}: {e}"
            async with AsyncSessionFactory() as session:
                await self._update_project_status(session, project_id, "failed", error_msg)
            logger.error("Pipeline échoué pour le projet %s : %s", project_id, e)
            raise

    async def _run_creation_pipeline(
        self, ctx: PipelineContext, start_from: str | None = None
    ) -> None:
        max_iterations = ctx.max_iterations_override or ctx.channel_config.max_critic_iterations
        await self._run_main_loop(ctx, start_from=start_from, max_iterations=max_iterations)

    async def _run_shorts_only_pipeline(
        self, ctx: PipelineContext, start_from: str | None = None
    ) -> None:
        base_max = ctx.max_iterations_override or ctx.channel_config.max_critic_iterations
        await self._run_main_loop(ctx, start_from=start_from, max_iterations=min(base_max, 2))

    async def _run_main_loop(
        self,
        ctx: PipelineContext,
        *,
        start_from: str | None,
        max_iterations: int,
    ) -> None:
        from agent.agents.research_agent import ResearchAgent
        from agent.agents.scenario_agent import ScenarioAgent
        from agent.agents.revision_agent import RevisionAgent
        from agent.agents.media_agent import MediaAgent
        from agent.agents.narrator_agent import NarratorAgent
        from agent.agents.editor_agent import EditorAgent
        from agent.agents.subtitle_agent import SubtitleAgent
        from agent.agents.critic_agent import CriticAgent
        from agent.agents.video_analyst_agent import run_video_analysis
        from agent.core.config import settings

        _STEPS = ["research_agent", "scenario_agent", "media_agent", "narrator_agent", "editor_agent", "subtitle_agent", "critic_agent"]
        _STEP_TO_LOOP_IDX: dict[str, int] = {
            "research_agent": 0,
            "scenario_agent": 1,
            "media_agent":    1,
            "narrator_agent": 2,
            "editor_agent":   3,
        }
        effective_start = "editor_agent" if start_from == "subtitle_agent" else start_from
        start_idx = _STEPS.index(effective_start) if effective_start in _STEPS else 0

        pid = str(ctx.project_id)
        current_agent = "research_agent"
        try:
            scenario: Scenario | None = None
            if ctx.critic_feedback:
                pass  # RevisionAgent will build the revised scenario inside the loop
            elif start_idx == 0:
                await queue.set_agent_status(pid, "research_agent", "running")
                brief = await ResearchAgent().run(ctx)
                ctx.research_brief = brief.to_dict()
                await queue.set_agent_status(pid, "research_agent", "success")

                await queue.set_agent_status(pid, "scenario_agent", "running")
                scenario = await ScenarioAgent().run(ctx)
                await queue.set_agent_status(pid, "scenario_agent", "success")
            elif start_idx <= 1:
                if start_idx == 0:
                    await queue.set_agent_status(pid, "research_agent", "success")
                await queue.set_agent_status(pid, "scenario_agent", "running")
                scenario = await ScenarioAgent().run(ctx)
                await queue.set_agent_status(pid, "scenario_agent", "success")
            else:
                scenario = await self._load_latest_scenario(ctx.project_id)
                await queue.set_agent_status(pid, "research_agent", "success")
                await queue.set_agent_status(pid, "scenario_agent", "success")

            best_score = 0
            best_video_id: uuid.UUID | None = None
            video: Video | None = None

            for iteration in range(1, max_iterations + 1):
                await _raise_if_cancelled(ctx.project_id)
                ctx.iteration = iteration

                if iteration == 1 and ctx.critic_feedback is not None:
                    next_step = ctx.critic_start_from or "media_agent"
                    loop_start = _STEP_TO_LOOP_IDX.get(next_step, 1)
                    await self._clear_iteration_assets(ctx.project_id, start_from=next_step)
                    if next_step == "research_agent":
                        current_agent = "research_agent"
                        await queue.set_agent_status(pid, "research_agent", "running")
                        brief = await ResearchAgent().run(ctx)
                        ctx.research_brief = brief.to_dict()
                        await queue.set_agent_status(pid, "research_agent", "success")
                        current_agent = "scenario_agent"
                        await queue.set_agent_status(pid, "scenario_agent", "running")
                        scenario = await ScenarioAgent().run(ctx)
                        await queue.set_agent_status(pid, "scenario_agent", "success")
                    else:
                        current_agent = "revision_agent"
                        await queue.set_agent_status(pid, "revision_agent", "running")
                        base = await self._load_latest_scenario(ctx.project_id)
                        if next_step != "editor_agent":
                            scenario = await RevisionAgent().run(ctx, base)
                        else:
                            scenario = base
                        await queue.set_agent_status(pid, "revision_agent", "success")
                elif iteration > 1:
                    next_step = ctx.critic_start_from or "media_agent"
                    loop_start = _STEP_TO_LOOP_IDX.get(next_step, 1)
                    await self._clear_iteration_assets(ctx.project_id, start_from=next_step)
                    if next_step == "research_agent":
                        current_agent = "research_agent"
                        await queue.set_agent_status(pid, "research_agent", "running")
                        brief = await ResearchAgent().run(ctx)
                        ctx.research_brief = brief.to_dict()
                        await queue.set_agent_status(pid, "research_agent", "success")
                        current_agent = "scenario_agent"
                        await queue.set_agent_status(pid, "scenario_agent", "running")
                        scenario = await ScenarioAgent().run(ctx)
                        await queue.set_agent_status(pid, "scenario_agent", "success")
                    elif next_step != "editor_agent":
                        current_agent = "revision_agent"
                        await queue.set_agent_status(pid, "revision_agent", "running")
                        scenario = await RevisionAgent().run(ctx, scenario)  # type: ignore[arg-type]
                        await queue.set_agent_status(pid, "revision_agent", "success")
                else:
                    loop_start = start_idx

                current_agent = "media_agent"
                if loop_start <= 1:
                    await queue.set_agent_status(pid, current_agent, "running")
                    await MediaAgent().run(ctx, scenario)
                    await queue.set_agent_status(pid, current_agent, "success")

                current_agent = "narrator_agent"
                if loop_start <= 2:
                    await queue.set_agent_status(pid, current_agent, "running")
                    await NarratorAgent().run(ctx, scenario)
                    await queue.set_agent_status(pid, current_agent, "success")

                current_agent = "editor_agent"
                if loop_start <= 3:
                    await queue.set_agent_status(pid, current_agent, "running")
                    video = await EditorAgent().run(ctx, scenario)
                    await queue.set_agent_status(pid, current_agent, "success")
                elif iteration == 1:
                    video = await self._load_latest_video(ctx.project_id)
                    await queue.set_agent_status(pid, "editor_agent", "success")

                current_agent = "subtitle_agent"
                if loop_start <= 4:
                    await queue.set_agent_status(pid, current_agent, "running")
                    await SubtitleAgent().run(ctx, video)
                    video = await self._load_latest_video(ctx.project_id)
                    await queue.set_agent_status(pid, current_agent, "success")

                video_analysis = None
                gemini_status = "missing_key"
                if settings.google_gemini_api_key and video.local_path:
                    if Path(video.local_path).exists():
                        video_analysis = await run_video_analysis(
                            video_path=video.local_path,
                            channel_name=ctx.channel.name,
                            theme=ctx.theme,
                            duration_s=video.duration_s or 0,
                            iteration=iteration,
                            api_key=settings.google_gemini_api_key,
                        )
                        gemini_status = "ok" if video_analysis else "error"
                    else:
                        gemini_status = "file_not_found"

                current_agent = "critic_agent"
                await queue.set_agent_status(pid, current_agent, "running")
                report = await CriticAgent().run(
                    ctx, video, scenario, iteration, video_analysis, gemini_status=gemini_status
                )
                await queue.set_agent_status(pid, current_agent, "success")

                score = report.global_score or 0
                if score > best_score:
                    best_score = score
                    best_video_id = video.id

                if report.decision == "approve":
                    break
                await self._apply_critic_changes(ctx, report, scenario)

            if best_video_id and video and best_video_id != video.id:
                await self._promote_best_video(best_video_id, video.id)

        except asyncio.CancelledError:
            await queue.set_agent_status(pid, current_agent, "stopped")
            raise
        except Exception:
            await queue.set_agent_status(pid, current_agent, "failed")
            raise

    async def _run_platform_exports(self, ctx: PipelineContext) -> None:
        from agent.agents.short_editor_agent import ShortEditorAgent

        await _raise_if_cancelled(ctx.project_id)
        pid = str(ctx.project_id)
        current_agent = "short_editor_agent"
        try:
            await queue.set_agent_status(pid, current_agent, "running")
            await ShortEditorAgent().run_platform_exports(ctx)
            await queue.set_agent_status(pid, current_agent, "success")
        except asyncio.CancelledError:
            await queue.set_agent_status(pid, current_agent, "stopped")
            raise
        except Exception:
            await queue.set_agent_status(pid, current_agent, "failed")
            raise

    async def _run_shorts_pipeline(
        self,
        ctx: PipelineContext,
        start_from: str | None = None,
        *,
        teaser_only: bool = False,
    ) -> None:
        from agent.agents.clipper_agent import ClipperAgent
        from agent.agents.short_editor_agent import ShortEditorAgent

        await _raise_if_cancelled(ctx.project_id)
        pid = str(ctx.project_id)
        current_agent = "clipper_agent"
        max_clips = (
            ctx.channel_config.short_derivation.hybrid_teaser_max_clips
            if teaser_only
            else None
        )
        try:
            # clipper output is in-memory only → always re-run even when start_from=short_editor_agent
            await queue.set_agent_status(pid, current_agent, "running")
            clips = await ClipperAgent().run(ctx, max_clips=max_clips)
            await queue.set_agent_status(pid, current_agent, "success")

            current_agent = "short_editor_agent"
            await queue.set_agent_status(pid, current_agent, "running")
            await ShortEditorAgent().run(ctx, clips)
            await queue.set_agent_status(pid, current_agent, "success")

        except asyncio.CancelledError:
            await queue.set_agent_status(pid, current_agent, "stopped")
            raise
        except Exception:
            await queue.set_agent_status(pid, current_agent, "failed")
            raise

    async def _run_native_shorts_pipeline(
        self,
        ctx: PipelineContext,
        *,
        planned_only: bool = False,
    ) -> None:
        from agent.agents.editor_agent import EditorAgent
        from agent.agents.media_agent import MediaAgent
        from agent.agents.narrator_agent import NarratorAgent
        from agent.agents.short_editor_agent import ShortEditorAgent
        from agent.agents.short_producer_agent import ShortProducerAgent

        pid = str(ctx.project_id)
        ctx.short_derivation_mode = ctx.channel_config.short_derivation.mode
        current_agent = "short_producer_agent"
        try:
            await queue.set_agent_status(pid, current_agent, "running")
            plans = await ShortProducerAgent().run(ctx, planned_only=planned_only)
            await queue.set_agent_status(pid, current_agent, "success")

            if not plans:
                logger.info("Aucun short natif à produire pour le projet %s", ctx.project_id)
                return

            for plan in plans:
                ctx.derivation_short_index = plan.index

                current_agent = "media_agent"
                await queue.set_agent_status(pid, current_agent, "running")
                await MediaAgent().run_derivation(ctx, plan)
                await queue.set_agent_status(pid, current_agent, "success")

                current_agent = "narrator_agent"
                await queue.set_agent_status(pid, current_agent, "running")
                await NarratorAgent().run_derivation(ctx, plan)
                await queue.set_agent_status(pid, current_agent, "success")

                current_agent = "editor_agent"
                await queue.set_agent_status(pid, current_agent, "running")
                await EditorAgent().run_derivation(ctx, plan)
                await queue.set_agent_status(pid, current_agent, "success")

            ctx.derivation_short_index = None

            current_agent = "short_editor_agent"
            await queue.set_agent_status(pid, current_agent, "running")
            await ShortEditorAgent().run_native_exports(ctx)
            await queue.set_agent_status(pid, current_agent, "success")

        except asyncio.CancelledError:
            await queue.set_agent_status(pid, current_agent, "stopped")
            raise
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
        ctx.critic_feedback = report.requested_changes
        ctx.critic_start_from = (report.feedback or {}).get("start_from") or "media_agent"
        for change in report.requested_changes:
            logger.info("Changement demandé pour %s : %s", change.get("agent"), change.get("change_description"))
        logger.info("Point de reprise : %s", ctx.critic_start_from)

    @staticmethod
    async def _clear_iteration_assets(project_id: uuid.UUID, start_from: str = "scenario_agent") -> None:
        """Nettoyage sélectif des assets selon le point de reprise du pipeline."""
        from sqlalchemy import delete as sa_delete

        clear_scenarios = start_from in ("research_agent", "scenario_agent")
        clear_media = start_from in ("research_agent", "scenario_agent", "media_agent")
        clear_audio = start_from in ("research_agent", "scenario_agent", "media_agent", "narrator_agent")

        async with AsyncSessionFactory() as session:
            if clear_scenarios:
                from sqlalchemy import delete as sa_delete
                await session.execute(
                    sa_delete(Scenario).where(Scenario.project_id == project_id)
                )
            if clear_media:
                from agent.skills.media.media_library import archive_current_selection

                await archive_current_selection(project_id)
            if clear_audio:
                await session.execute(
                    sa_delete(AudioFile).where(AudioFile.project_id == project_id)
                )
            await session.commit()

        logger.info(
            "Assets nettoyés (start_from=%s, scenarios=%s, media=%s, audio=%s) pour %s",
            start_from, clear_scenarios, clear_media, clear_audio, project_id,
        )

    @staticmethod
    async def _promote_best_video(best_video_id: uuid.UUID, last_video_id: uuid.UUID) -> None:
        """Mark the best-scoring video as approved; delete intermediate iteration videos."""
        from pathlib import Path as _Path
        from sqlalchemy import update as sa_update
        from agent.core.storage import delete_s3_object

        async with AsyncSessionFactory() as session:
            await session.execute(
                sa_update(Video)
                .where(Video.id == best_video_id)
                .values(status="approved")
            )
            await session.commit()

            best = await session.get(Video, best_video_id)
            if best is None:
                return
            intermediates_result = await session.execute(
                select(Video).where(
                    Video.project_id == best.project_id,
                    Video.video_type.in_(["long", "short_master"]),
                    Video.id != best_video_id,
                )
            )
            intermediates = intermediates_result.scalars().all()
            for v in intermediates:
                if v.storage_key:
                    try:
                        await delete_s3_object(v.storage_key)
                    except Exception:
                        logger.warning("Échec suppression S3 pour vidéo intermédiaire %s", v.id)
                if v.local_path:
                    local = _Path(v.local_path)
                    if local.exists():
                        local.unlink(missing_ok=True)
                await session.delete(v)
            await session.commit()

        logger.info(
            "Meilleure vidéo promue : %s — %d vidéo(s) intermédiaire(s) supprimée(s)",
            best_video_id,
            len(intermediates),
        )

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

    @staticmethod
    async def _load_latest_scenario(project_id: uuid.UUID) -> Scenario:
        async with AsyncSessionFactory() as session:
            result = await session.execute(
                select(Scenario)
                .where(Scenario.project_id == project_id)
                .order_by(Scenario.created_at.desc())
                .limit(1)
            )
            scenario = result.scalar_one_or_none()
            if not scenario:
                raise RuntimeError(
                    f"Aucun scénario en base pour le projet {project_id} — "
                    "impossible de reprendre depuis cette étape"
                )
            return scenario

    @staticmethod
    async def _load_latest_video(project_id: uuid.UUID) -> Video:
        async with AsyncSessionFactory() as session:
            result = await session.execute(
                select(Video)
                .where(
                    Video.project_id == project_id,
                    Video.video_type.in_(["long", "short_master"]),
                )
                .order_by(Video.created_at.desc())
                .limit(1)
            )
            video = result.scalar_one_or_none()
            if not video:
                raise RuntimeError(
                    f"Aucune vidéo principale (long/short_master) pour le projet {project_id} — "
                    "impossible de reprendre depuis subtitle_agent ou critic_agent"
                )
            return video
