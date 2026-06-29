from __future__ import annotations

import logging
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from agent.core.base_agent import BaseAgent
from agent.core.concurrency import bounded_gather
from agent.core.database import AsyncSessionFactory, MediaAsset, Project, Scenario
from agent.core.media_validation import resolve_validation_brief
from agent.core.storage import cleanup_temp_ai_images
from agent.skills.media.ai_image_result import MediaGap
from agent.skills.media.asset_resolver import resolve_search_anchor
from agent.skills.media.run_session import MediaRunSession, init_provider_keys
from agent.skills.media.scenario_media_gap import adapt_scenario_for_media_gaps
from agent.skills.media.segment_classic import process_segment_classic

if TYPE_CHECKING:
    from agent.core.orchestrator import PipelineContext
    from agent.core.short_derivation import DerivedShortPlan

logger = logging.getLogger(__name__)


class MediaAgent(BaseAgent):
    """Agent 2 — Chercheur média : trouve les images/vidéos libres de droits."""

    name = "media_agent"

    def _new_session(self) -> MediaRunSession:
        session = MediaRunSession()
        session.bind_agent(self)
        return session

    async def run(self, ctx: PipelineContext, scenario: Scenario) -> list[MediaAsset]:  # type: ignore[override]
        run = await self.start_run(
            ctx.project_id, {"scenario_id": str(scenario.id)}, iteration=ctx.iteration
        )
        session = self._new_session()
        try:
            assets = await self._search_all_segments(ctx, scenario, session, mode="main")
            output: dict[str, Any] = {
                "assets_count": len(assets),
                "relevance_scores": session.relevance_log,
                **self._build_media_run_stats(
                    assets, ai_images_used=session.ai_images_used
                ),
            }
            if session.media_gaps:
                output["media_gaps"] = [g.to_dict() for g in session.media_gaps]
                adapted, adapted_orders = await adapt_scenario_for_media_gaps(
                    scenario,
                    session.media_gaps,
                    theme=ctx.theme,
                    user_id=ctx.user_id,
                )
                scenario.segments = adapted.segments
                if adapted.total_duration_s is not None:
                    scenario.total_duration_s = adapted.total_duration_s
                output["adapted_segments"] = adapted_orders
            await cleanup_temp_ai_images(
                ctx.project_id,
                keep_keys=session.kept_temp_s3_keys,
            )
            await self.end_run(run, output)
            return assets
        except Exception as e:
            await self.fail_run(run, e)
            raise

    async def run_derivation(
        self, ctx: PipelineContext, plan: DerivedShortPlan
    ) -> list[MediaAsset]:
        from agent.skills.media.short_derivation import run_media_for_short_derivation

        run = await self.start_run(
            ctx.project_id,
            {"derivation_index": plan.index, "mode": "short_derivation"},
        )
        session = self._new_session()
        try:
            assets = await run_media_for_short_derivation(self, ctx, plan, session)
            await self.end_run(
                run,
                {
                    "assets_count": len(assets),
                    **self._build_media_run_stats(
                        assets, ai_images_used=session.ai_images_used
                    ),
                },
            )
            return assets
        except Exception as e:
            await self.fail_run(run, e)
            raise

    @staticmethod
    def _requires_vertical(ctx: PipelineContext) -> bool:
        from agent.core.short_format import requires_vertical_output

        return requires_vertical_output(ctx)

    @staticmethod
    def _is_derivation(ctx: PipelineContext) -> bool:
        return ctx.derivation_short_index is not None

    @staticmethod
    def _resolve_search_orientation(ctx: PipelineContext) -> str:
        if MediaAgent._is_derivation(ctx) or MediaAgent._requires_vertical(ctx):
            return "portrait"
        return "landscape"

    @staticmethod
    def _build_media_run_stats(
        assets: list[MediaAsset],
        *,
        ai_images_used: int = 0,
    ) -> dict[str, int]:
        return {
            "video_assets_count": sum(1 for a in assets if a.asset_type == "video"),
            "image_assets_count": sum(
                1 for a in assets if a.asset_type != "video" and a.source != "ai_image"
            ),
            "ai_generated_count": sum(1 for a in assets if a.source == "ai_image"),
            "ai_images_used": ai_images_used,
            "coverr_hits": sum(1 for a in assets if a.source == "coverr"),
        }

    @staticmethod
    def _derivation_media_dir(ctx: PipelineContext, order: int) -> Path:
        idx = ctx.derivation_short_index or 0
        return Path(f"./tmp/{ctx.project_id}/shorts/{idx:02d}/media/segment_{order:02d}")

    @staticmethod
    def _derivation_allows_ai(ctx: PipelineContext) -> bool:
        return ctx.short_derivation_mode == "full"

    @staticmethod
    def _derivation_allows_external_search(ctx: PipelineContext) -> bool:
        return ctx.short_derivation_mode in ("free_sources_only", "full")

    @staticmethod
    def _derivation_sources(sources: list[str]) -> list[str]:
        return [s for s in sources if s != "ai"]

    @staticmethod
    def _derivation_iteration_value(ctx: PipelineContext) -> int:
        from agent.core.short_derivation import derivation_iteration

        return derivation_iteration(ctx.derivation_short_index or 0)

    def _media_iteration(self, ctx: PipelineContext) -> int:
        if self._is_derivation(ctx):
            return self._derivation_iteration_value(ctx)
        return ctx.iteration

    async def _search_all_segments(
        self,
        ctx: PipelineContext,
        scenario: Scenario,
        session: MediaRunSession,
        *,
        mode: Literal["main", "derivation"] = "main",
    ) -> list[MediaAsset]:
        from agent.skills.media_sources.relevance_scorer import MediaRelevanceScoringError

        await init_provider_keys(self, ctx, session)
        segments = scenario.segments or []
        if mode == "derivation":
            sources = self._derivation_sources(ctx.channel_config.media_source_priority)
        else:
            sources = ctx.channel_config.media_source_priority
        ms_cfg = ctx.channel_config.media_sources
        ai_cfg = ctx.channel_config.ai_fallback
        all_assets: list[MediaAsset] = []

        project_config: dict[str, Any] = {}
        async with AsyncSessionFactory() as db:
            from sqlalchemy import select

            result = await db.execute(select(Project).where(Project.id == ctx.project_id))
            project = result.scalar_one_or_none()
            if project and project.config:
                project_config = dict(project.config)

        validation_brief = resolve_validation_brief(
            channel_config=ctx.channel.config or {},
            project_config=project_config,
            scenario_segments=segments,
            theme_category=ctx.theme_category,
        )

        session.ai_images_used = 0
        session.perception_calls_used = 0
        session.runway_clips_used = 0
        session.validation_brief = validation_brief
        session.search_orientation = self._resolve_search_orientation(ctx)
        await resolve_search_anchor(session, ctx, validation_brief)
        session.bind_agent(self)

        lib_cfg = ctx.channel_config.media_library
        if mode == "main" and lib_cfg.enabled:
            from agent.skills.media.media_library import archive_current_selection

            await archive_current_selection(ctx.project_id)

        pool_assets: list[MediaAsset] = []
        if lib_cfg.enabled:
            from agent.skills.media.media_library import query_pool

            pool_assets = await query_pool(ctx.project_id)

        tasks = [
            self._process_segment(
                ctx, segment, sources, ms_cfg, ai_cfg, validation_brief, pool_assets, session
            )
            for segment in segments
        ]
        results = await bounded_gather(*tasks, return_exceptions=True)

        for result in results:
            if isinstance(result, MediaRelevanceScoringError):
                raise result

        failed_segments: list[int] = []
        label = "dérivé" if mode == "derivation" else ""
        for i, result in enumerate(results):
            if isinstance(result, list):
                all_assets.extend(result)
            elif isinstance(result, Exception):
                logger.warning("Erreur segment %s %d : %s", label, i, result)
                failed_segments.append(i)

        if failed_segments:
            first_error = next(r for r in results if isinstance(r, Exception))
            if len(failed_segments) == len(segments):
                raise first_error from None
            suffix = f" dérivé(s)" if mode == "derivation" else " retenu"
            raise RuntimeError(
                f"{len(failed_segments)}/{len(segments)} segment(s){suffix} sans média. "
                f"Détail : {first_error}"
            ) from first_error

        if mode == "main" and session.media_gaps:
            await self._persist_media_gaps(ctx.project_id, session.media_gaps)

        return all_assets

    async def _search_all_segments_derivation(
        self, ctx: PipelineContext, scenario: Scenario, session: MediaRunSession
    ) -> list[MediaAsset]:
        return await self._search_all_segments(ctx, scenario, session, mode="derivation")

    @staticmethod
    async def _persist_media_gaps(
        project_id: uuid.UUID,
        gaps: list[MediaGap],
    ) -> None:
        from sqlalchemy import select

        async with AsyncSessionFactory() as db:
            result = await db.execute(select(Project).where(Project.id == project_id))
            project = result.scalar_one_or_none()
            if project is None:
                return
            config = dict(project.config or {})
            config["media_gaps"] = [g.to_dict() for g in gaps]
            project.config = config
            await db.commit()

    async def _process_segment(
        self,
        ctx: PipelineContext,
        segment: dict,
        sources: list[str],
        ms_cfg: Any,
        ai_cfg: Any,
        validation_brief: Any,
        pool_assets: list[MediaAsset] | None,
        session: MediaRunSession,
    ) -> list[MediaAsset]:
        from agent.core.visual_beats import parse_visual_beats
        from agent.skills.media.segment_beats_media import process_segment_beats

        vb_cfg = ctx.channel_config.visual_beats
        beats = parse_visual_beats(segment) if vb_cfg.enabled else []
        if vb_cfg.enabled and beats:
            assets = await process_segment_beats(
                self,
                session,
                ctx,
                segment,
                sources,
                ms_cfg,
                ai_cfg,
                validation_brief,
                pool_assets or [],
            )
            if assets:
                return assets
            logger.warning(
                "Segment %s : beats sans média — fallback mode segment classique",
                segment.get("order"),
            )

        return await process_segment_classic(
            self,
            session,
            ctx,
            segment,
            sources,
            ms_cfg,
            ai_cfg,
            validation_brief,
            is_derivation=self._is_derivation(ctx),
            derivation_allows_external_search=self._derivation_allows_external_search(ctx),
            derivation_allows_ai=self._derivation_allows_ai(ctx),
            derivation_sources_fn=self._derivation_sources,
            derivation_media_dir_fn=self._derivation_media_dir,
            requires_vertical=self._requires_vertical(ctx),
            media_iteration=self._media_iteration(ctx),
        )
