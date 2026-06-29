from __future__ import annotations

import logging
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Any

from agent.core.config import get_storage_settings
from agent.core.media_validation import MediaValidationBrief
from agent.core.storage import (
    build_temp_ai_storage_key,
    delete_s3_objects,
    register_temp_ai_key,
    upload_media_file,
)
from agent.core.visual_beats import VisualBeat, beat_narration_excerpt
from agent.skills.media.ai_image_result import AiImageResult, MediaGap
from agent.skills.media.scenario_media_gap import ai_fallback_attempt_config
from agent.skills.media_sources.ai.prompt_builder import is_diagram_visual_type
from agent.skills.media_sources.ai.subject_bible import beat_subject_seed, seed_for_attempt
from agent.skills.media_sources.relevance_scorer import (
    is_text_artifact_rejection,
    score_media_candidates,
)
from agent.skills.media.rights_check import enrich_candidate, is_publishable

if TYPE_CHECKING:
    from agent.core.orchestrator import PipelineContext
    from agent.skills.media.run_session import MediaRunSession

logger = logging.getLogger(__name__)


def effective_max_ai_images(session: MediaRunSession, ai_cfg: Any) -> int:
    base = int(ai_cfg.max_ai_images_per_video)
    brief = session.validation_brief
    if brief is not None and getattr(brief, "niche_risk", "") == "high":
        return max(base, 15)
    return base


async def can_generate_ai_image(
    session: MediaRunSession,
    ctx: PipelineContext,
    ai_cfg: Any,
) -> bool:
    if ai_cfg.plan.value == "off" or not ai_cfg.enabled:
        return False
    max_per_video = effective_max_ai_images(session, ai_cfg)
    if session.ai_images_used >= max_per_video:
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


async def record_ai_image_usage(ctx: PipelineContext) -> None:
    from agent.core.ai_image_budget import increment_weekly_ai_image_count

    await increment_weekly_ai_image_count(
        str(ctx.channel_id),
        timezone=ctx.channel_config.timezone,
    )


async def generate_ai_fallback(
    session: MediaRunSession,
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
    seed: int | None = None,
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
        fal_api_key=session.fal_api_key,
        gcp_credentials=session.gcp_credentials,
        seed=seed,
    )


async def upload_ai_candidate_temp(
    session: MediaRunSession,
    ctx: PipelineContext,
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


async def cleanup_ai_candidates(
    session: MediaRunSession,
    candidates: list[tuple[dict, int, str, str, str | None, str]],
    *,
    winner_item: dict,
) -> None:
    winner_local = str(winner_item.get("local_generated") or "")
    winner_key = winner_item.get("_temp_s3_key")
    if winner_key:
        session.kept_temp_s3_keys.append(str(winner_key))

    keys_to_delete: list[str] = []
    for item, _, _, _, temp_key, _ in candidates:
        item_local = str(item.get("local_generated") or "")
        if item_local and item_local != winner_local:
            Path(item_local).unlink(missing_ok=True)
        if temp_key and temp_key != winner_key:
            keys_to_delete.append(temp_key)
    if keys_to_delete and get_storage_settings().bucket:
        await delete_s3_objects(keys_to_delete)


async def generate_validated_ai_image(
    session: MediaRunSession,
    ai_prompt: str,
    output_dir: Path,
    ctx: PipelineContext,
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
    dev_plan, dev_attempts, paid_attempts = ai_fallback_attempt_config()
    paid_plan = ai_cfg.plan.value
    effective_visual_type = visual_type or (beat.visual_type if beat else "")
    if is_diagram_visual_type(effective_visual_type):
        paid_plan = dev_plan
    order = segment.get("order", 0)
    total_attempts = dev_attempts + paid_attempts

    base_seed: int | None = None
    if not is_diagram_visual_type(effective_visual_type):
        beat_text = f"{ai_prompt} {getattr(beat, 'phrase_anchor', '') if beat else ''}"
        base_seed = beat_subject_seed(validation_brief.subject_entity, beat_text)

    candidates: list[tuple[dict, int, str, str, str | None, str]] = []
    phases: list[tuple[str, str, int]] = [
        ("dev", dev_plan, dev_attempts),
        ("paid", paid_plan, paid_attempts),
    ]

    gen_index = 0
    for phase, plan_id, max_t in phases:
        for attempt in range(1, max_t + 1):
            gen_index += 1
            ai_item = await generate_ai_fallback(
                session,
                ai_prompt,
                output_dir,
                ctx.theme_category,
                ctx.channel_config.editorial_tone,
                ai_cfg=ai_cfg,
                aspect_ratio=aspect_ratio,
                plan_override=plan_id,
                use_prompt_as_is=use_prompt_as_is,
                visual_type=visual_type or (beat.visual_type if beat else ""),
                seed=seed_for_attempt(base_seed, gen_index),
            )
            if not ai_item:
                session.relevance_log.append({
                    "segment_order": order,
                    "source": "ai_generated",
                    "phase": phase,
                    "attempt": attempt,
                    "generation_failed": True,
                })
                continue
            ai_item["_generation_prompt"] = ai_prompt

            temp_key = await upload_ai_candidate_temp(session, ctx, order, ai_item)

            scored = await score_media_candidates(
                [ai_item],
                video_subject=ctx.theme,
                channel_category=ctx.theme_category,
                segment_title=segment.get("title", ""),
                segment_narration=(
                    beat_narration_excerpt(beat)
                    if beat is not None
                    else (segment.get("narration_text") or "")[:500]
                ),
                api_key=session.gemini_api_key,
                cache_dir=output_dir / "scoring",
                validation_brief=validation_brief,
                segment_order=order,
                beat=beat,
                scoring_models=session.scoring_models,
            )
            score = scored[0].score if scored else 0
            reason = scored[0].reason if scored else ""
            rejection_category = scored[0].rejection_category if scored else "ok"
            session.relevance_log.append({
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
                await cleanup_ai_candidates(session, candidates, winner_item=ai_item)
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
                await cleanup_ai_candidates(session, candidates, winner_item=best_item)
                return AiImageResult(outcome="api_failed")
        floor = ctx.channel_config.media_sources.forced_best_min_score
        if best_score < floor:
            logger.warning(
                "Segment %d : forced_best refusé (score %d < plancher %d) — gap",
                order, best_score, floor,
            )
            await cleanup_ai_candidates(session, candidates, winner_item=best_item)
            return AiImageResult(outcome="api_failed")
        best_item["_relevance_validated"] = False
        best_item["_relevance_forced_fallback"] = True
        best_item["_relevance_score"] = best_score
        best_item["_relevance_reason"] = best_reason
        if best_key:
            best_item["_temp_s3_key"] = best_key
        session.relevance_log.append({
            "segment_order": order,
            "source": "ai_generated",
            "phase": "best_score_fallback",
            "score": best_score,
            "from_phase": best_phase,
        })
        await cleanup_ai_candidates(session, candidates, winner_item=best_item)
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


async def apply_ai_image_result(
    session: MediaRunSession,
    result: AiImageResult,
    *,
    ctx: PipelineContext,
    segment: dict,
    ai_prompt: str,
    selected: list[dict],
    dev_attempts: int,
    paid_attempts: int,
    count_toward_video_quota: bool = True,
) -> None:
    order = int(segment.get("order", 0))
    if result.outcome == "api_failed":
        gap = MediaGap(
            segment_order=order,
            reason="ai_generation_failed",
            attempts=dev_attempts + paid_attempts,
            prompt=ai_prompt,
        )
        session.media_gaps.append(gap)
        session.segment_media_gaps.add(order)
        return
    if result.item:
        item = enrich_candidate(result.item)
        ok, reason = is_publishable(item)
        if not ok:
            logger.warning(
                "Segment %d : image IA refusée (licence) — %s",
                order,
                reason,
            )
            gap = MediaGap(
                segment_order=order,
                reason=f"ai_license_rejected:{reason}",
                attempts=dev_attempts + paid_attempts,
                prompt=ai_prompt,
            )
            session.media_gaps.append(gap)
            session.segment_media_gaps.add(order)
            return
        selected.append(item)
        if count_toward_video_quota:
            session.ai_images_used += 1
            await record_ai_image_usage(ctx)
        if result.temp_s3_key and result.temp_s3_key not in session.kept_temp_s3_keys:
            session.kept_temp_s3_keys.append(result.temp_s3_key)
