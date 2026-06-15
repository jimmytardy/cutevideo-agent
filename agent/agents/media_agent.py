from __future__ import annotations

import asyncio
import json
import logging
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Any

from agent.core.api_keys import fetch_api_key, parse_gcp_credentials
from agent.core.base_agent import BaseAgent
from agent.core.config import get_storage_settings
from agent.core.database import AsyncSessionFactory, MediaAsset, Project, Scenario
from agent.core.media_validation import MediaValidationBrief, resolve_validation_brief
from agent.core.storage import (
    build_temp_ai_storage_key,
    cleanup_temp_ai_images,
    register_temp_ai_key,
    upload_media_file,
)
from agent.skills.media.ai_image_result import AiImageResult, MediaGap
from agent.skills.media.scenario_media_gap import (
    adapt_scenario_for_media_gaps,
    ai_fallback_attempt_config,
)

if TYPE_CHECKING:
    from agent.core.visual_beats import VisualBeat

logger = logging.getLogger(__name__)

_GENERIC_KEYWORDS = frozenset({
    "nature", "animal", "animaux", "bird", "birds", "oiseau", "oiseaux",
    "histoire", "history", "science", "landscape", "paysage", "wildlife",
})


class MediaAgent(BaseAgent):
    """Agent 2 — Chercheur média : trouve les images/vidéos libres de droits."""

    name = "media_agent"

    async def run(self, ctx: "PipelineContext", scenario: Scenario) -> list[MediaAsset]:  # type: ignore[override]
        run = await self.start_run(
            ctx.project_id, {"scenario_id": str(scenario.id)}, iteration=ctx.iteration
        )
        self._relevance_log = []
        self._media_gaps = []
        self._kept_temp_s3_keys: list[str] = []
        self._segment_media_gaps: set[int] = set()
        try:
            assets = await self._search_all_segments(ctx, scenario)
            output: dict[str, Any] = {
                "assets_count": len(assets),
                "relevance_scores": self._relevance_log,
            }
            if self._media_gaps:
                output["media_gaps"] = [g.to_dict() for g in self._media_gaps]
                adapted, adapted_orders = await adapt_scenario_for_media_gaps(
                    scenario,
                    self._media_gaps,
                    theme=ctx.theme,
                    user_id=ctx.user_id,
                )
                scenario.segments = adapted.segments
                if adapted.total_duration_s is not None:
                    scenario.total_duration_s = adapted.total_duration_s
                output["adapted_segments"] = adapted_orders
            await cleanup_temp_ai_images(
                ctx.project_id,
                keep_keys=self._kept_temp_s3_keys,
            )
            await self.end_run(run, output)
            return assets
        except Exception as e:
            await self.fail_run(run, e)
            raise

    async def run_derivation(
        self, ctx: "PipelineContext", plan: "DerivedShortPlan"
    ) -> list[MediaAsset]:
        from agent.skills.media.short_derivation import run_media_for_short_derivation

        run = await self.start_run(
            ctx.project_id,
            {"derivation_index": plan.index, "mode": "short_derivation"},
        )
        self._relevance_log = []
        self._media_gaps = []
        self._kept_temp_s3_keys = []
        self._segment_media_gaps = set()
        try:
            assets = await run_media_for_short_derivation(self, ctx, plan)
            await self.end_run(run, {"assets_count": len(assets)})
            return assets
        except Exception as e:
            await self.fail_run(run, e)
            raise

    @staticmethod
    def _is_derivation(ctx: "PipelineContext") -> bool:
        return ctx.derivation_short_index is not None

    @staticmethod
    def _derivation_media_dir(ctx: "PipelineContext", order: int) -> Path:
        idx = ctx.derivation_short_index or 0
        return Path(f"./tmp/{ctx.project_id}/shorts/{idx:02d}/media/segment_{order:02d}")

    @staticmethod
    def _derivation_allows_ai(ctx: "PipelineContext") -> bool:
        return ctx.short_derivation_mode == "full"

    @staticmethod
    def _derivation_allows_external_search(ctx: "PipelineContext") -> bool:
        return ctx.short_derivation_mode in ("free_sources_only", "full")

    @staticmethod
    def _derivation_sources(sources: list[str]) -> list[str]:
        return [s for s in sources if s != "ai"]

    @staticmethod
    def _derivation_iteration_value(ctx: "PipelineContext") -> int:
        from agent.core.short_derivation import derivation_iteration

        return derivation_iteration(ctx.derivation_short_index or 0)

    def _media_iteration(self, ctx: "PipelineContext") -> int:
        if self._is_derivation(ctx):
            return self._derivation_iteration_value(ctx)
        return ctx.iteration

    async def _init_provider_keys(self, ctx: "PipelineContext") -> None:
        """Charge les clés API résolues pour l'utilisateur propriétaire de la chaîne."""
        from agent.core.agent_llm_constraints import normalize_agent_preference
        from agent.core.llm_resolver import parse_agent_preferences
        from agent.skills.media_sources.relevance_scorer import resolve_scoring_model_chain

        gemini_ctx = await fetch_api_key(
            ctx.user_id, "gemini", purpose="media_relevance_scoring", tier="free"
        )
        self._gemini_api_key = gemini_ctx.key or ""

        scoring_model: str | None = None
        if ctx.user_id is not None:
            async with AsyncSessionFactory() as session:
                from agent.core.database import User

                user = await session.get(User, ctx.user_id)
                if user:
                    prefs = parse_agent_preferences(user.agent_llm_preferences)
                    pref = prefs.get("media_agent_llm")
                    if pref:
                        normalized = normalize_agent_preference("media_agent_llm", pref)
                        scoring_model = normalized.model
        self._scoring_models = resolve_scoring_model_chain(scoring_model)
        fal_ctx = await fetch_api_key(ctx.user_id, "fal", purpose="ai_image", tier="paid")
        self._fal_api_key = fal_ctx.key
        runway_ctx = await fetch_api_key(
            ctx.user_id, "runway", purpose="ai_video", tier="paid"
        )
        self._runway_api_key = runway_ctx.key
        gcp_ctx = await fetch_api_key(ctx.user_id, "gcp", purpose="ai_image", tier="paid")
        self._gcp_credentials = parse_gcp_credentials(gcp_ctx)

    async def _search_all_segments_derivation(
        self, ctx: "PipelineContext", scenario: Scenario
    ) -> list[MediaAsset]:
        from agent.skills.media_sources.relevance_scorer import MediaRelevanceScoringError

        await self._init_provider_keys(ctx)
        segments = scenario.segments or []
        sources = self._derivation_sources(ctx.channel_config.media_source_priority)
        ms_cfg = ctx.channel_config.media_sources
        ai_cfg = ctx.channel_config.ai_fallback
        all_assets: list[MediaAsset] = []

        project_config: dict[str, Any] = {}
        async with AsyncSessionFactory() as session:
            from sqlalchemy import select

            result = await session.execute(
                select(Project).where(Project.id == ctx.project_id)
            )
            project = result.scalar_one_or_none()
            if project and project.config:
                project_config = dict(project.config)

        validation_brief = resolve_validation_brief(
            channel_config=ctx.channel.config or {},
            project_config=project_config,
            scenario_segments=segments,
            theme_category=ctx.theme_category,
        )

        self._ai_images_used = 0
        self._runway_clips_used = 0
        self._validation_brief = validation_brief

        pool_assets: list[MediaAsset] = []
        if ctx.channel_config.media_library.enabled:
            from agent.skills.media.media_library import query_pool

            pool_assets = await query_pool(ctx.project_id)

        tasks = [
            self._process_segment(
                ctx, segment, sources, ms_cfg, ai_cfg, validation_brief, pool_assets
            )
            for segment in segments
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for result in results:
            if isinstance(result, MediaRelevanceScoringError):
                raise result

        failed_segments: list[int] = []
        for i, result in enumerate(results):
            if isinstance(result, list):
                all_assets.extend(result)
            elif isinstance(result, Exception):
                logger.warning("Erreur segment dérivé %d : %s", i, result)
                failed_segments.append(i)

        if failed_segments:
            first_error = next(r for r in results if isinstance(r, Exception))
            if len(failed_segments) == len(segments):
                raise first_error from None
            raise RuntimeError(
                f"{len(failed_segments)}/{len(segments)} segment(s) dérivé(s) sans média. "
                f"Détail : {first_error}"
            ) from first_error

        return all_assets

    async def _search_all_segments(
        self, ctx: "PipelineContext", scenario: Scenario
    ) -> list[MediaAsset]:
        from agent.skills.media_sources.relevance_scorer import MediaRelevanceScoringError

        await self._init_provider_keys(ctx)
        segments = scenario.segments or []
        sources = ctx.channel_config.media_source_priority
        ms_cfg = ctx.channel_config.media_sources
        ai_cfg = ctx.channel_config.ai_fallback
        all_assets: list[MediaAsset] = []

        project_config: dict[str, Any] = {}
        async with AsyncSessionFactory() as session:
            from sqlalchemy import select

            result = await session.execute(
                select(Project).where(Project.id == ctx.project_id)
            )
            project = result.scalar_one_or_none()
            if project and project.config:
                project_config = dict(project.config)

        validation_brief = resolve_validation_brief(
            channel_config=ctx.channel.config or {},
            project_config=project_config,
            scenario_segments=segments,
            theme_category=ctx.theme_category,
        )

        self._ai_images_used = 0
        self._runway_clips_used = 0
        self._validation_brief = validation_brief

        lib_cfg = ctx.channel_config.media_library
        if lib_cfg.enabled:
            from agent.skills.media.media_library import archive_current_selection

            await archive_current_selection(ctx.project_id)

        pool_assets: list[MediaAsset] = []
        if lib_cfg.enabled:
            from agent.skills.media.media_library import query_pool

            pool_assets = await query_pool(ctx.project_id)

        tasks = [
            self._process_segment(
                ctx, segment, sources, ms_cfg, ai_cfg, validation_brief, pool_assets
            )
            for segment in segments
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for result in results:
            if isinstance(result, MediaRelevanceScoringError):
                raise result

        failed_segments: list[int] = []
        for i, result in enumerate(results):
            if isinstance(result, list):
                all_assets.extend(result)
            elif isinstance(result, Exception):
                logger.warning("Erreur segment %d : %s", i, result)
                failed_segments.append(i)

        if failed_segments:
            first_error = next(r for r in results if isinstance(r, Exception))
            if len(failed_segments) == len(segments):
                raise first_error from None
            raise RuntimeError(
                f"{len(failed_segments)}/{len(segments)} segment(s) sans média retenu. "
                f"Détail : {first_error}"
            ) from first_error

        if self._media_gaps:
            await self._persist_media_gaps(ctx.project_id, self._media_gaps)

        return all_assets

    @staticmethod
    def _asset_key(item: dict) -> str:
        return str(item.get("local_generated") or item.get("url") or "")

    async def _filter_candidates_by_relevance(
        self,
        candidates: list[dict],
        *,
        ctx: "PipelineContext",
        segment: dict,
        min_relevance: int,
        output_dir: Path,
        segment_order: int,
        validation_brief: MediaValidationBrief,
        attempt: int = 1,
        beat: VisualBeat | None = None,
    ) -> tuple[list[dict], list[dict]]:
        from agent.skills.media_sources.relevance_scorer import score_media_candidates

        narration = (segment.get("narration_text") or "")[:500]
        if beat is not None:
            narration = f"{beat.phrase_anchor} — {beat.prompt}"

        scored = await score_media_candidates(
            candidates,
            video_subject=ctx.theme,
            channel_category=ctx.theme_category,
            segment_title=segment.get("title", ""),
            segment_narration=narration,
            api_key=self._gemini_api_key,
            cache_dir=output_dir / "scoring",
            validation_brief=validation_brief,
            segment_order=segment_order,
            beat=beat,
            scoring_models=getattr(self, "_scoring_models", None),
        )
        log_entry: dict[str, Any] = {
            "segment_order": segment_order,
            "attempt": attempt,
            "scores": [
                {
                    "score": s.score,
                    "reason": s.reason,
                    "rejection_category": s.rejection_category,
                    "title": s.candidate.get("title"),
                    "url": s.candidate.get("url"),
                }
                for s in scored[:10]
            ],
        }
        if beat is not None:
            log_entry["beat_order"] = beat.order
            log_entry["visual_type"] = beat.visual_type
        self._relevance_log.append(log_entry)
        above_threshold: list[dict] = []
        rejected: list[dict] = []
        for s in scored:
            item = dict(s.candidate)
            item["_relevance_score"] = s.score
            item["_relevance_reason"] = s.reason
            item["_rejection_category"] = s.rejection_category
            if s.score >= min_relevance:
                item["_relevance_validated"] = True
                above_threshold.append(item)
            else:
                rejected.append(item)
        if not above_threshold:
            logger.warning(
                "Segment %d tentative %d : aucun candidat >= %d",
                segment_order,
                attempt,
                min_relevance,
            )
        return above_threshold, rejected

    async def _generate_validated_ai_image(
        self,
        ai_prompt: str,
        output_dir: Path,
        ctx: "PipelineContext",
        segment: dict,
        min_relevance: int,
        ai_cfg: Any,
        aspect_ratio: str,
        validation_brief: MediaValidationBrief,
        *,
        use_prompt_as_is: bool = False,
        beat: VisualBeat | None = None,
        visual_type: str = "",
    ) -> AiImageResult:
        """Génère une image IA (dev puis payant), valide via Gemini, best-score en dernier recours."""
        from agent.skills.media_sources.ai.prompt_builder import is_diagram_visual_type
        from agent.skills.media_sources.relevance_scorer import is_text_artifact_rejection, score_media_candidates

        dev_plan, dev_attempts, paid_attempts = ai_fallback_attempt_config()
        paid_plan = ai_cfg.plan.value
        order = segment.get("order", 0)
        total_attempts = dev_attempts + paid_attempts

        candidates: list[tuple[dict, int, str, str, str | None, str]] = []

        phases: list[tuple[str, str, int]] = [
            ("dev", dev_plan, dev_attempts),
            ("paid", paid_plan, paid_attempts),
        ]

        for phase, plan_id, max_t in phases:
            for attempt in range(1, max_t + 1):
                ai_item = await self._generate_ai_fallback(
                    ai_prompt,
                    output_dir,
                    ctx.theme_category,
                    ctx.channel_config.editorial_tone,
                    ai_cfg=ai_cfg,
                    aspect_ratio=aspect_ratio,
                    plan_override=plan_id,
                    use_prompt_as_is=use_prompt_as_is,
                    visual_type=visual_type or (beat.visual_type if beat else ""),
                )
                if not ai_item:
                    self._relevance_log.append({
                        "segment_order": order,
                        "source": "ai_generated",
                        "phase": phase,
                        "attempt": attempt,
                        "generation_failed": True,
                    })
                    continue
                ai_item["_generation_prompt"] = ai_prompt

                temp_key = await self._upload_ai_candidate_temp(
                    ctx, order, ai_item,
                )

                scored = await score_media_candidates(
                    [ai_item],
                    video_subject=ctx.theme,
                    channel_category=ctx.theme_category,
                    segment_title=segment.get("title", ""),
                    segment_narration=(
                        f"{beat.phrase_anchor} — {beat.prompt}"
                        if beat is not None
                        else (segment.get("narration_text") or "")[:500]
                    ),
                    api_key=self._gemini_api_key,
                    cache_dir=output_dir / "scoring",
                    validation_brief=validation_brief,
                    segment_order=order,
                    beat=beat,
                    scoring_models=getattr(self, "_scoring_models", None),
                )
                score = scored[0].score if scored else 0
                reason = scored[0].reason if scored else ""
                rejection_category = scored[0].rejection_category if scored else "ok"
                self._relevance_log.append({
                    "segment_order": order,
                    "scores": [{
                        "score": score,
                        "reason": reason,
                        "title": ai_item.get("title"),
                        "url": ai_item.get("url"),
                    }],
                    "source": "ai_generated",
                    "phase": phase,
                    "attempt": attempt,
                })

                candidates.append((ai_item, score, reason, phase, temp_key, rejection_category))

                if score >= min_relevance:
                    if beat and is_diagram_visual_type(beat.visual_type):
                        if is_text_artifact_rejection(rejection_category, reason):
                            logger.warning(
                                "Segment %d beat diagramme : image rejetée (artefact texte : %s)",
                                order,
                                reason,
                            )
                            continue
                    ai_item["_relevance_validated"] = True
                    ai_item["_relevance_score"] = score
                    ai_item["_relevance_reason"] = reason
                    if temp_key:
                        ai_item["_temp_s3_key"] = temp_key
                    await self._cleanup_ai_candidates(candidates, winner_item=ai_item)
                    return AiImageResult(
                        outcome="validated",
                        item=ai_item,
                        temp_s3_key=temp_key,
                    )

                logger.warning(
                    "Segment %d : image IA %s tentative %d/%d rejetée (score %d/%d)",
                    order, phase, attempt, max_t, score, min_relevance,
                )

        if candidates:
            best_item, best_score, best_reason, best_phase, best_key, best_category = max(
                candidates, key=lambda c: c[1]
            )
            if beat and is_diagram_visual_type(beat.visual_type):
                if is_text_artifact_rejection(best_category, best_reason):
                    logger.warning(
                        "Segment %d beat diagramme : forced_best refusé (artefact texte : %s)",
                        order,
                        best_reason,
                    )
                    await self._cleanup_ai_candidates(candidates, winner_item=best_item)
                    return AiImageResult(outcome="api_failed")
            best_item["_relevance_validated"] = False
            best_item["_relevance_forced_fallback"] = True
            best_item["_relevance_score"] = best_score
            best_item["_relevance_reason"] = best_reason
            if best_key:
                best_item["_temp_s3_key"] = best_key
            self._relevance_log.append({
                "segment_order": order,
                "source": "ai_generated",
                "phase": "best_score_fallback",
                "score": best_score,
                "from_phase": best_phase,
            })
            await self._cleanup_ai_candidates(candidates, winner_item=best_item)
            return AiImageResult(
                outcome="forced_best",
                item=best_item,
                temp_s3_key=best_key,
            )

        logger.warning(
            "Segment %d : échec total génération IA (%d tentatives API)",
            order, total_attempts,
        )
        return AiImageResult(outcome="api_failed")

    async def _upload_ai_candidate_temp(
        self,
        ctx: "PipelineContext",
        segment_order: int,
        ai_item: dict,
    ) -> str | None:
        local = ai_item.get("local_generated")
        if not local or not Path(local).exists():
            return None
        if not get_storage_settings().bucket:
            return None
        candidate_id = uuid.uuid4().hex[:12]
        key = build_temp_ai_storage_key(
            ctx.channel.slug,
            str(ctx.project_id),
            segment_order,
            candidate_id,
        )
        await upload_media_file(Path(local), key, content_type="image/jpeg")
        await register_temp_ai_key(ctx.project_id, key)
        return key

    async def _cleanup_ai_candidates(
        self,
        candidates: list[tuple[dict, int, str, str, str | None, str]],
        *,
        winner_item: dict,
    ) -> None:
        winner_local = str(winner_item.get("local_generated") or "")
        winner_key = winner_item.get("_temp_s3_key")
        if winner_key:
            self._kept_temp_s3_keys.append(str(winner_key))

        from agent.core.storage import delete_s3_objects

        keys_to_delete: list[str] = []
        for item, _, _, _, temp_key, _ in candidates:
            item_local = str(item.get("local_generated") or "")
            if item_local and item_local != winner_local:
                Path(item_local).unlink(missing_ok=True)
            if temp_key and temp_key != winner_key:
                keys_to_delete.append(temp_key)
        if keys_to_delete and get_storage_settings().bucket:
            await delete_s3_objects(keys_to_delete)

    @staticmethod
    async def _persist_media_gaps(
        project_id: uuid.UUID,
        gaps: list[MediaGap],
    ) -> None:
        from sqlalchemy import select

        async with AsyncSessionFactory() as session:
            result = await session.execute(select(Project).where(Project.id == project_id))
            project = result.scalar_one_or_none()
            if project is None:
                return
            config = dict(project.config or {})
            config["media_gaps"] = [g.to_dict() for g in gaps]
            project.config = config
            await session.commit()

    async def _apply_ai_image_result(
        self,
        result: AiImageResult,
        *,
        ctx: "PipelineContext",
        segment: dict,
        ai_prompt: str,
        selected: list[dict],
        dev_attempts: int,
        paid_attempts: int,
    ) -> None:
        order = int(segment.get("order", 0))
        if result.outcome == "api_failed":
            gap = MediaGap(
                segment_order=order,
                reason="ai_generation_failed",
                attempts=dev_attempts + paid_attempts,
                prompt=ai_prompt,
            )
            self._media_gaps.append(gap)
            self._segment_media_gaps.add(order)
            return
        if result.item:
            selected.append(result.item)
            self._ai_images_used += 1
            await self._record_ai_image_usage(ctx)
            if result.temp_s3_key and result.temp_s3_key not in self._kept_temp_s3_keys:
                self._kept_temp_s3_keys.append(result.temp_s3_key)

    async def _validate_single_asset(
        self,
        item: dict,
        *,
        ctx: "PipelineContext",
        segment: dict,
        min_relevance: int,
        output_dir: Path,
        validation_brief: MediaValidationBrief,
    ) -> dict | None:
        passing, _ = await self._filter_candidates_by_relevance(
            [item],
            ctx=ctx,
            segment=segment,
            min_relevance=min_relevance,
            output_dir=output_dir,
            segment_order=int(segment.get("order", 0)),
            validation_brief=validation_brief,
            attempt=0,
        )
        return passing[0] if passing else None

    async def _audit_selected_media(
        self,
        selected: list[dict],
        *,
        ctx: "PipelineContext",
        segment: dict,
        min_relevance: int,
        output_dir: Path,
        validation_brief: MediaValidationBrief,
        assets_needed: int,
        video_target: int,
    ) -> list[dict]:
        audited: list[dict] = []
        for item in selected:
            if item.get("_relevance_validated"):
                audited.append(item)
                continue
            validated = await self._validate_single_asset(
                item,
                ctx=ctx,
                segment=segment,
                min_relevance=min_relevance,
                output_dir=output_dir,
                validation_brief=validation_brief,
            )
            if validated:
                audited.append(validated)
        return self._select_assets(audited, video_target, assets_needed)

    async def _search_segment_with_iterations(
        self,
        *,
        ctx: "PipelineContext",
        segment: dict,
        sources: list[str],
        ms_cfg: Any,
        keywords: list[str],
        period: str,
        effective_sources: list[str],
        assets_needed: int,
        video_target: int,
        min_candidates: int,
        min_relevance: int,
        output_dir: Path,
        validation_brief: MediaValidationBrief,
        order: int,
        beat: VisualBeat | None = None,
    ) -> list[dict]:
        max_iterations = ms_cfg.max_search_iterations
        passing_target = max(
            assets_needed,
            int(assets_needed * ms_cfg.min_passing_candidates_multiplier),
        )
        rejected_urls: set[str] = set()
        all_passing: list[dict] = []
        current_keywords = list(keywords)
        validation_relaxed = False
        total_raw_candidates = 0

        for attempt in range(1, max_iterations + 1):
            effective_min = min_relevance
            if (
                validation_brief.niche_risk == "high"
                and attempt == max_iterations
                and not all_passing
            ):
                effective_min = max(50, min_relevance - 10)
                validation_relaxed = True

            video_candidates: list[dict] = []
            if video_target > 0:
                video_candidates = await self._search_with_fallback(
                    effective_sources,
                    current_keywords,
                    period,
                    segment,
                    min_candidates,
                    video_subject=ctx.theme,
                    media_type="video",
                    exclude_urls=rejected_urls,
                )
                video_candidates = self._dedupe_and_filter(
                    video_candidates, ms_cfg.min_width_px, exclude_urls=rejected_urls
                )

            image_candidates = await self._search_with_fallback(
                effective_sources,
                current_keywords,
                period,
                segment,
                max(min_candidates, assets_needed),
                video_subject=ctx.theme,
                media_type="image",
                exclude_urls=rejected_urls,
            )
            image_candidates = self._dedupe_and_filter(
                image_candidates, ms_cfg.min_width_px, exclude_urls=rejected_urls
            )

            candidates = video_candidates + image_candidates
            total_raw_candidates += len(candidates)
            if not candidates:
                refined = await self._llm_refined_keywords(
                    segment, ctx.theme, validation_brief, [], attempt
                )
                if refined:
                    current_keywords = refined[0]
                continue

            passing, rejected = await self._filter_candidates_by_relevance(
                candidates,
                ctx=ctx,
                segment=segment,
                min_relevance=effective_min,
                output_dir=output_dir,
                segment_order=order,
                validation_brief=validation_brief,
                attempt=attempt,
                beat=beat,
            )
            for item in rejected:
                url = item.get("url") or item.get("local_generated") or ""
                if url:
                    rejected_urls.add(str(url))
            seen = {self._asset_key(p) for p in all_passing}
            for item in passing:
                key = self._asset_key(item)
                if key and key not in seen:
                    seen.add(key)
                    all_passing.append(item)

            if len(all_passing) >= passing_target:
                break

            rejection_reasons = [
                f"{r.get('_rejection_category', 'off_topic')}: {r.get('_relevance_reason', '')}"
                for r in rejected[:8]
            ]
            refined_lists = await self._llm_refined_keywords(
                segment, ctx.theme, validation_brief, rejection_reasons, attempt
            )
            if refined_lists:
                current_keywords = refined_lists[0]

        if validation_relaxed:
            self._relevance_log.append({
                "segment_order": order,
                "validation_relaxed": True,
            })

        self._relevance_log.append({
            "segment_order": order,
            "total_raw_candidates": total_raw_candidates,
            "passing_count": len(all_passing),
            "niche_risk": validation_brief.niche_risk,
        })
        return all_passing

    async def _process_segment(
        self,
        ctx: "PipelineContext",
        segment: dict,
        sources: list[str],
        ms_cfg: Any,
        ai_cfg: Any,
        validation_brief: MediaValidationBrief,
        pool_assets: list[MediaAsset] | None = None,
    ) -> list[MediaAsset]:
        from agent.core.visual_beats import parse_visual_beats
        from agent.skills.media.segment_beats_media import process_segment_beats

        vb_cfg = ctx.channel_config.visual_beats
        beats = parse_visual_beats(segment) if vb_cfg.enabled else []
        if vb_cfg.enabled and beats:
            assets = await process_segment_beats(
                self,
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

        keywords = segment.get("search_keywords", [])
        period = segment.get("historical_period", "")
        order = segment.get("order", 0)
        assets_needed = ms_cfg.images_per_segment
        video_target = (
            min(ms_cfg.video_clips_per_segment, assets_needed)
            if ms_cfg.prefer_video
            else 0
        )
        image_target = assets_needed - video_target
        min_candidates = ms_cfg.min_candidates_per_segment
        min_relevance = validation_brief.min_score_for_segment(order)
        _, dev_attempts, paid_attempts = ai_fallback_attempt_config()

        hint = segment.get("source_hint") or []
        if hint:
            seen = set(hint)
            effective_sources = list(hint) + [s for s in sources if s not in seen]
        else:
            effective_sources = sources

        output_dir = (
            self._derivation_media_dir(ctx, order)
            if self._is_derivation(ctx)
            else Path(f"./tmp/{ctx.project_id}/media/segment_{order:02d}")
        )

        if self._is_derivation(ctx) and not self._derivation_allows_external_search(ctx):
            candidates: list[dict] = []
        else:
            search_sources = (
                self._derivation_sources(effective_sources)
                if self._is_derivation(ctx)
                else effective_sources
            )
            candidates = await self._search_segment_with_iterations(
                ctx=ctx,
                segment=segment,
                sources=sources,
                ms_cfg=ms_cfg,
                keywords=keywords,
                period=period,
                effective_sources=search_sources,
                assets_needed=assets_needed,
                video_target=video_target,
                min_candidates=min_candidates,
                min_relevance=min_relevance,
                output_dir=output_dir,
                validation_brief=validation_brief,
                order=order,
            )

        selected = self._select_assets(candidates, video_target, assets_needed)

        niche_early_ai = (
            validation_brief.niche_risk == "high"
            or len(candidates) < ms_cfg.niche_threshold_candidates
        )
        selected_videos = sum(1 for item in selected if item.get("asset_type") == "video")
        selected_images = len(selected) - selected_videos

        if (
            (selected_images < image_target or niche_early_ai)
            and ms_cfg.enable_ai_fallback
            and ai_cfg.enabled
            and (not self._is_derivation(ctx) or self._derivation_allows_ai(ctx))
        ):
            missing = max(image_target - selected_images, 0)
            if niche_early_ai and missing == 0:
                missing = max(1, image_target)
            ai_prompt = (
                f"{ctx.theme} — {segment.get('title', '')} — "
                f"{validation_brief.subject_entity} — {' '.join(keywords[:3])}"
            )
            aspect_ratio = (
                "9:16"
                if ctx.channel_config.production_mode == "shorts_only" or self._is_derivation(ctx)
                else "16:9"
            )
            max_segment_ai = min(missing or image_target, ai_cfg.max_images_per_segment)
            for _ in range(max_segment_ai):
                if not await self._can_generate_ai_image(ctx, ai_cfg):
                    break
                ai_result = await self._generate_validated_ai_image(
                    ai_prompt,
                    output_dir,
                    ctx,
                    segment,
                    min_relevance,
                    ai_cfg,
                    aspect_ratio,
                    validation_brief,
                )
                await self._apply_ai_image_result(
                    ai_result,
                    ctx=ctx,
                    segment=segment,
                    ai_prompt=ai_prompt,
                    selected=selected,
                    dev_attempts=dev_attempts,
                    paid_attempts=paid_attempts,
                )

        runway_cfg = ctx.channel_config.runway
        missing_videos = video_target - sum(
            1 for item in selected if item.get("asset_type") == "video"
        )
        if (
            missing_videos > 0
            and runway_cfg.enabled
            and self._runway_clips_used < runway_cfg.max_clips_per_video
            and (not self._is_derivation(ctx) or self._derivation_allows_ai(ctx))
        ):
            runway_prompt = (
                f"{ctx.theme} — {segment.get('title', '')} — "
                f"{validation_brief.subject_entity} — {' '.join(keywords[:4])}"
            )
            for _ in range(missing_videos):
                if self._runway_clips_used >= runway_cfg.max_clips_per_video:
                    break
                runway_item = await self._generate_runway_clip(
                    runway_prompt, output_dir, runway_cfg, ctx
                )
                if runway_item:
                    validated = await self._validate_single_asset(
                        runway_item,
                        ctx=ctx,
                        segment=segment,
                        min_relevance=min_relevance,
                        output_dir=output_dir,
                        validation_brief=validation_brief,
                    )
                    if validated:
                        selected.append(validated)
                        self._runway_clips_used += 1

        if (
            len(selected) < assets_needed
            and ms_cfg.enable_ai_fallback
            and ai_cfg.enabled
            and (not self._is_derivation(ctx) or self._derivation_allows_ai(ctx))
        ):
            remaining = assets_needed - len(selected)
            ai_prompt = (
                f"{ctx.theme} — {segment.get('title', '')} — "
                f"{validation_brief.subject_entity} — {' '.join(keywords[:3])}"
            )
            aspect_ratio = (
                "9:16"
                if ctx.channel_config.production_mode == "shorts_only" or self._is_derivation(ctx)
                else "16:9"
            )
            for _ in range(min(remaining, ai_cfg.max_images_per_segment)):
                if len(selected) >= assets_needed:
                    break
                if not await self._can_generate_ai_image(ctx, ai_cfg):
                    break
                ai_result = await self._generate_validated_ai_image(
                    ai_prompt,
                    output_dir,
                    ctx,
                    segment,
                    min_relevance,
                    ai_cfg,
                    aspect_ratio,
                    validation_brief,
                )
                await self._apply_ai_image_result(
                    ai_result,
                    ctx=ctx,
                    segment=segment,
                    ai_prompt=ai_prompt,
                    selected=selected,
                    dev_attempts=dev_attempts,
                    paid_attempts=paid_attempts,
                )

        if ms_cfg.enable_post_selection_audit and selected:
            selected = await self._audit_selected_media(
                selected,
                ctx=ctx,
                segment=segment,
                min_relevance=min_relevance,
                output_dir=output_dir,
                validation_brief=validation_brief,
                assets_needed=assets_needed,
                video_target=video_target,
            )

        selected = selected[:assets_needed]
        assets: list[MediaAsset] = []
        output_dir.mkdir(parents=True, exist_ok=True)

        async with AsyncSessionFactory() as session:
            for item in selected:
                is_video = item.get("asset_type") == "video"
                local_path = await self._download_asset(item, output_dir)
                asset = MediaAsset(
                    project_id=ctx.project_id,
                    segment_order=order,
                    source=item.get("source"),
                    source_url=item.get("url"),
                    local_path=str(local_path) if local_path else item.get("local_generated"),
                    license=item.get("license"),
                    attribution=item.get("attribution"),
                    asset_type="video" if is_video else "image",
                    selected=True,
                    relevance_score=item.get("_relevance_score"),
                    relevance_reason=item.get("_relevance_reason"),
                    library_status="selected",
                    generation_prompt=item.get("title"),
                    visual_type=None,
                    iteration=self._media_iteration(ctx),
                )
                session.add(asset)
                assets.append(asset)
            await session.commit()

        logger.info(
            "Segment %d : %d médias (%d vidéos, %d images)",
            order,
            len(assets),
            sum(1 for a in assets if a.asset_type == "video"),
            sum(1 for a in assets if a.asset_type != "video"),
        )
        if not assets:
            title = segment.get("title", "")
            if order in self._segment_media_gaps:
                logger.warning(
                    "Segment %d (« %s ») : aucun média visuel — gap IA, scénario adapté",
                    order, title,
                )
                return assets
            raise RuntimeError(
                f"Segment {order} (« {title} ») : aucun média retenu "
                f"(seuil de pertinence ≥ {min_relevance}). "
                "Vérifiez les mots-clés, les sources média ou abaissez relevance_min_score."
            )
        return assets

    @staticmethod
    def _select_assets(
        candidates: list[dict],
        video_target: int,
        total_needed: int,
    ) -> list[dict]:
        """Priorise les clips vidéo stock, complète avec des images."""
        videos = [c for c in candidates if c.get("asset_type") == "video"]
        images = [c for c in candidates if c.get("asset_type") != "video"]
        picked_videos = videos[:video_target]
        image_slots = max(0, total_needed - len(picked_videos))
        return (picked_videos + images[:image_slots])[:total_needed]

    @staticmethod
    def _build_anchored_queries(
        keywords: list[str],
        video_subject: str,
        segment_title: str,
    ) -> list[list[str]]:
        anchor = (video_subject or segment_title or "").strip()
        queries: list[list[str]] = []
        if keywords:
            queries.append([k for k in keywords[:4] if k])
        if anchor:
            if keywords:
                for kw in keywords[:2]:
                    if kw and kw.lower() not in _GENERIC_KEYWORDS:
                        queries.append([anchor, kw])
            queries.append([anchor])
        seen: set[tuple[str, ...]] = set()
        unique: list[list[str]] = []
        for q in queries:
            key = tuple(q)
            if key and key not in seen:
                seen.add(key)
                unique.append(q)
        return unique

    async def _generate_runway_clip(
        self,
        prompt: str,
        output_dir: Path,
        runway_cfg: Any,
        ctx: "PipelineContext",
    ) -> dict | None:
        from agent.skills.media_sources.runway import generate_video_clip

        return await generate_video_clip(
            prompt,
            output_dir,
            runway_cfg=runway_cfg,
            channel_id=str(ctx.channel_id),
            timezone=ctx.channel_config.timezone,
            api_key=self._runway_api_key,
        )

    async def _search_with_fallback(
        self,
        sources: list[str],
        keywords: list[str],
        period: str,
        segment: dict,
        min_candidates: int,
        *,
        video_subject: str,
        media_type: str = "image",
        exclude_urls: set[str] | None = None,
    ) -> list[dict]:
        candidates: list[dict] = []
        fallback_sources = sources[:2]
        excluded = exclude_urls or set()

        for source in sources:
            try:
                found = await self._search_source(source, keywords, period, media_type=media_type)
                candidates.extend(found)
                if len(candidates) >= min_candidates * 2:
                    break
            except Exception as e:
                logger.warning("Source %s (%s) échouée : %s", source, media_type, e)

        candidates = self._dedupe_and_filter(candidates, 0, exclude_urls=excluded)
        if len(candidates) >= min_candidates:
            return candidates

        anchored = self._build_anchored_queries(
            keywords, video_subject, segment.get("title", "")
        )
        for kw_list in anchored:
            for source in fallback_sources:
                try:
                    found = await self._search_source(source, kw_list, "", media_type=media_type)
                    candidates.extend(found)
                except Exception:
                    pass
            candidates = self._dedupe_and_filter(candidates, 0, exclude_urls=excluded)
            if len(candidates) >= min_candidates:
                return candidates

        alt_keywords = await self._llm_alternative_keywords(segment, video_subject)
        for kw_list in alt_keywords:
            for source in fallback_sources:
                try:
                    found = await self._search_source(source, kw_list, "", media_type=media_type)
                    candidates.extend(found)
                except Exception:
                    pass
            candidates = self._dedupe_and_filter(candidates, 0, exclude_urls=excluded)
            if len(candidates) >= min_candidates:
                break

        return candidates

    async def _llm_refined_keywords(
        self,
        segment: dict,
        video_subject: str,
        validation_brief: MediaValidationBrief,
        rejection_reasons: list[str],
        attempt: int,
    ) -> list[list[str]]:
        narration = segment.get("narration_text", "")[:800]
        title = segment.get("title", "")
        reasons_text = "\n".join(f"- {r}" for r in rejection_reasons[:8]) or "(aucun)"
        prompt = (
            f"Sujet vidéo : {video_subject}\n"
            f"Entité précise : {validation_brief.subject_entity}\n"
            f"Segment : {title}\n{narration}\n"
            f"Tentative de recherche : {attempt}\n"
            f"DOIT montrer : {', '.join(validation_brief.must_include)}\n"
            f"NE DOIT PAS montrer : {', '.join(validation_brief.must_exclude)}\n"
            f"Rejets précédents :\n{reasons_text}\n"
            "Génère 3 listes de 2-5 mots-clés (FR/EN) pour trouver de MEILLEURS visuels stock. "
            "Évite les termes qui ont produit des rejets. Inclus le nom précis du sujet.\n"
            'Retourne UNIQUEMENT JSON : {"queries": [["kw1","kw2"], ...]}'
        )
        try:
            raw = await self._call_claude(prompt, model="claude-sonnet-4-5", max_tokens=256)
            if raw.startswith("```"):
                raw = raw.split("\n", 1)[1].rsplit("```", 1)[0]
            data = json.loads(raw)
            queries = data.get("queries", [])
            return [[str(k) for k in q] for q in queries if isinstance(q, list)]
        except Exception as e:
            logger.warning("LLM refined keywords échoué : %s", e)
            return []

    async def _llm_alternative_keywords(
        self, segment: dict, video_subject: str
    ) -> list[list[str]]:
        narration = segment.get("narration_text", "")[:800]
        title = segment.get("title", "")
        prompt = (
            f"Sujet de la vidéo : {video_subject}\n"
            f"Segment : {title}\n{narration}\n"
            "Génère 3 listes de 2-4 mots-clés de recherche image (FR/EN) pour trouver des visuels "
            "libres STRICTEMENT liés au sujet de la vidéo et au segment. "
            "Chaque liste doit inclure un terme précis du sujet (nom propre, lieu, concept, espèce…). "
            "Interdit : requêtes purement catégorielles (ex. seulement « nature », « animal », « history »). "
            'Retourne UNIQUEMENT JSON : {"queries": [["kw1","kw2"], ...]}'
        )

        try:
            raw = await self._call_claude(prompt, model="claude-sonnet-4-5", max_tokens=256)
            if raw.startswith("```"):
                raw = raw.split("\n", 1)[1].rsplit("```", 1)[0]
            data = json.loads(raw)
            queries = data.get("queries", [])
            return [[str(k) for k in q] for q in queries if isinstance(q, list)]
        except Exception as e:
            logger.warning("LLM keywords fallback échoué : %s", e)
            return []

    @staticmethod
    def _dedupe_and_filter(
        candidates: list[dict],
        min_width: int,
        *,
        exclude_urls: set[str] | None = None,
    ) -> list[dict]:
        seen: set[str] = set()
        excluded = exclude_urls or set()
        filtered: list[dict] = []
        for item in candidates:
            url = item.get("url", "") or item.get("local_generated", "")
            if not url or url in seen or str(url) in excluded:
                continue
            width = item.get("width")
            if min_width and width and int(width) < min_width:
                continue
            seen.add(url)
            filtered.append(item)
        return filtered

    async def _search_source(
        self,
        source: str,
        keywords: list[str],
        period: str,
        *,
        media_type: str = "image",
    ) -> list[dict]:
        from agent.skills.media_sources import (
            europeana,
            gallica,
            internet_archive,
            nasa,
            pexels,
            pixabay,
            unsplash,
            wikimedia,
        )

        source_map = {
            "wikimedia": wikimedia.search,
            "gallica": gallica.search,
            "europeana": europeana.search,
            "unsplash": unsplash.search,
            "pexels": pexels.search,
            "pixabay": pixabay.search,
            "internet_archive": internet_archive.search,
            "nasa": nasa.search,
        }
        fn = source_map.get(source)
        if fn is None:
            return []
        return await fn(keywords, period, media_type=media_type)

    async def _can_generate_ai_image(self, ctx: "PipelineContext", ai_cfg: Any) -> bool:
        if ai_cfg.plan.value == "off" or not ai_cfg.enabled:
            return False
        max_per_video = self._effective_max_ai_images(ai_cfg)
        if self._ai_images_used >= max_per_video:
            logger.info("Plafond IA vidéo atteint (%d)", max_per_video)
            return False
        if ai_cfg.max_ai_images_per_week is None:
            return True
        from agent.core.ai_image_budget import get_weekly_ai_image_count

        weekly = await get_weekly_ai_image_count(
            str(ctx.channel_id),
            timezone=ctx.channel_config.timezone,
        )
        if weekly >= ai_cfg.max_ai_images_per_week:
            logger.info("Plafond IA hebdo chaîne atteint (%d)", ai_cfg.max_ai_images_per_week)
            return False
        return True

    def _effective_max_ai_images(self, ai_cfg: Any) -> int:
        base = int(ai_cfg.max_ai_images_per_video)
        brief = getattr(self, "_validation_brief", None)
        if brief is not None and getattr(brief, "niche_risk", "") == "high":
            return max(base, 15)
        return base

    async def _record_ai_image_usage(self, ctx: "PipelineContext") -> None:
        from agent.core.ai_image_budget import increment_weekly_ai_image_count

        await increment_weekly_ai_image_count(
            str(ctx.channel_id),
            timezone=ctx.channel_config.timezone,
        )

    async def _persist_beat_asset(
        self,
        *,
        ctx: "PipelineContext",
        item: dict,
        segment_order: int,
        beat: Any,
        output_dir: Path,
        generation_prompt: str,
    ) -> MediaAsset:
        from agent.core.visual_beats import VisualBeat

        assert isinstance(beat, VisualBeat)
        local_path = await self._download_asset(item, output_dir)
        duration_s = item.get("duration_s")
        clip_metadata = None
        path_obj = Path(local_path) if local_path else None
        if path_obj and path_obj.exists() and item.get("asset_type") == "video":
            duration_s, clip_metadata = await self._analyze_video_asset(
                ctx, path_obj, item, beat, segment_order,
            )
        async with AsyncSessionFactory() as session:
            asset = MediaAsset(
                project_id=ctx.project_id,
                segment_order=segment_order,
                beat_index=beat.order,
                source=item.get("source"),
                source_url=item.get("url"),
                local_path=str(local_path) if local_path else item.get("local_generated"),
                license=item.get("license"),
                attribution=item.get("attribution"),
                asset_type=item.get("asset_type", "image"),
                selected=True,
                relevance_score=item.get("_relevance_score"),
                relevance_reason=item.get("_relevance_reason"),
                library_status="selected",
                generation_prompt=generation_prompt,
                visual_type=beat.visual_type,
                iteration=self._media_iteration(ctx),
                duration_s=float(duration_s) if duration_s else None,
                clip_metadata=clip_metadata,
            )
            session.add(asset)
            await session.commit()
            await session.refresh(asset)
            return asset

    async def _persist_pool_candidate(
        self,
        ctx: "PipelineContext",
        item: dict,
        segment_order: int,
        beat: Any,
        output_dir: Path,
        pool_min_score: int,
    ) -> None:
        from agent.skills.media.media_library import promote_to_pool

        local_path = await self._download_asset(item, output_dir)
        async with AsyncSessionFactory() as session:
            asset = MediaAsset(
                project_id=ctx.project_id,
                segment_order=segment_order,
                beat_index=beat.order,
                source=item.get("source"),
                source_url=item.get("url"),
                local_path=str(local_path) if local_path else item.get("local_generated"),
                license=item.get("license"),
                attribution=item.get("attribution"),
                asset_type=item.get("asset_type", "image"),
                selected=False,
                relevance_score=item.get("_relevance_score"),
                relevance_reason=item.get("_relevance_reason"),
                library_status="pool",
                generation_prompt=item.get("_generation_prompt") or beat.prompt,
                visual_type=beat.visual_type,
                iteration=self._media_iteration(ctx),
            )
            await promote_to_pool(asset, pool_min_score=pool_min_score)
            session.add(asset)
            await session.commit()

    async def _analyze_video_asset(
        self,
        ctx: "PipelineContext",
        path: Path,
        item: dict,
        beat: Any,
        segment_order: int,
    ) -> tuple[float | None, dict | None]:
        from agent.skills.media.clip_source_analyzer import (
            analyze_clip_source,
            clip_metadata_to_dict,
        )
        from agent.skills.video.ffmpeg_utils import _probe_clip_duration

        try:
            duration = float(item.get("duration_s") or await _probe_clip_duration(path))
        except Exception:
            duration = None
        if not duration:
            return None, None
        if not self._gemini_api_key:
            return duration, None
        context = f"{beat.phrase_anchor} — {beat.prompt}"
        meta = await analyze_clip_source(
            path,
            context=context,
            duration_s=duration,
            api_key=self._gemini_api_key,
        )
        if meta and (meta.useful_duration_s or 0) < 3.0:
            logger.warning("Clip vidéo rejeté (durée utile < 3s) : %s", path)
            return duration, clip_metadata_to_dict(meta)
        return duration, clip_metadata_to_dict(meta) if meta else None

    async def _generate_ai_fallback(
        self,
        prompt: str,
        output_dir: Path,
        theme_category: str,
        editorial_tone: str,
        *,
        ai_cfg: Any,
        aspect_ratio: str = "16:9",
        plan_override: str | None = None,
        use_prompt_as_is: bool = False,
        visual_type: str = "",
    ) -> dict | None:
        from agent.skills.media_sources.ai_image import generate_image

        return await generate_image(
            prompt,
            output_dir,
            ai_cfg=ai_cfg,
            theme_category=theme_category,
            editorial_tone=editorial_tone,
            aspect_ratio=aspect_ratio,
            plan_override=plan_override,
            use_prompt_as_is=use_prompt_as_is,
            visual_type=visual_type,
            fal_api_key=self._fal_api_key,
            gcp_credentials=self._gcp_credentials,
        )

    @staticmethod
    async def _download_asset(item: dict, output_dir: Path) -> Path | None:
        if item.get("local_generated"):
            return Path(item["local_generated"])

        import aiohttp

        url = item.get("url")
        if not url or url.startswith("/"):
            return Path(url) if url and Path(url).exists() else None
        raw_name = url.split("/")[-1].split("?")[0] or ""
        if raw_name and "." in raw_name:
            filename = raw_name
        elif item.get("asset_type") == "video":
            filename = "clip.mp4"
        else:
            filename = "image.jpg"
        dest = output_dir / filename
        if dest.exists():
            return dest
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                    if resp.status == 200:
                        dest.write_bytes(await resp.read())
                        return dest
        except Exception as e:
            logger.warning("Téléchargement échoué %s : %s", url, e)
        return None
