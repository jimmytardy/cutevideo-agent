from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from agent.core.database import AsyncSessionFactory, MediaAsset
from agent.core.media_asset_resolve import clip_metadata_for_media_item
from agent.skills.media.ai_image_result import MediaGap
from agent.skills.media.asset_persistence import (
    apply_perception_batch,
    download_asset,
    rights_fields,
)
from agent.skills.media.asset_resolver import (
    anchored_keywords,
    search_segment_with_iterations,
    select_assets,
)
from agent.skills.media.asset_validation import audit_selected_media
from agent.skills.media.scenario_media_gap import ai_fallback_attempt_config
from agent.skills.media.segment_beats_media import synthesize_segment_ai_prompt
from agent.skills.media_sources.ai.routing import (
    apply_ai_image_result,
    can_generate_ai_image,
    generate_validated_ai_image,
)
from agent.skills.video.montage_profile import is_short_montage

if TYPE_CHECKING:
    from agent.agents.media_agent import MediaAgent
    from agent.core.media_validation import MediaValidationBrief
    from agent.core.orchestrator import PipelineContext
    from agent.skills.media.run_session import MediaRunSession

logger = logging.getLogger(__name__)


async def generate_runway_clip(
    session: MediaRunSession,
    prompt: str,
    output_dir: Path,
    runway_cfg: Any,
    ctx: PipelineContext,
) -> dict | None:
    from agent.skills.media_sources.runway import generate_video_clip

    return await generate_video_clip(
        prompt,
        output_dir,
        runway_cfg=runway_cfg,
        channel_id=str(ctx.channel_id),
        timezone=ctx.channel_config.timezone,
        api_key=session.runway_api_key,
    )


async def process_segment_classic(
    agent: MediaAgent,
    session: MediaRunSession,
    ctx: PipelineContext,
    segment: dict,
    sources: list[str],
    ms_cfg: Any,
    ai_cfg: Any,
    validation_brief: MediaValidationBrief,
    *,
    is_derivation: bool,
    derivation_allows_external_search: bool,
    derivation_allows_ai: bool,
    derivation_sources_fn: Any,
    derivation_media_dir_fn: Any,
    requires_vertical: bool,
    media_iteration: int,
) -> list[MediaAsset]:
    keywords = anchored_keywords(session, segment.get("search_keywords", []))
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
        derivation_media_dir_fn(ctx, order)
        if is_derivation
        else Path(f"./tmp/{ctx.project_id}/media/segment_{order:02d}")
    )

    if is_derivation and not derivation_allows_external_search:
        candidates: list[dict] = []
    else:
        search_sources = (
            derivation_sources_fn(effective_sources)
            if is_derivation
            else effective_sources
        )
        candidates = await search_segment_with_iterations(
            session,
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
            call_claude=agent._call_claude,
        )

    selected = select_assets(candidates, video_target, assets_needed)

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
        and (not is_derivation or derivation_allows_ai)
    ):
        missing = max(image_target - selected_images, 0)
        if niche_early_ai and missing == 0:
            missing = max(1, image_target)
        aspect_ratio = "9:16" if requires_vertical else "16:9"
        ai_prompt, ai_beat, ai_visual_type = await synthesize_segment_ai_prompt(
            session, ctx, segment, keywords,
            aspect_ratio=aspect_ratio,
            cache_dir=output_dir / "segment_prompt_cache",
        )
        max_segment_ai = min(missing or image_target, ai_cfg.max_images_per_segment)
        for _ in range(max_segment_ai):
            if not await can_generate_ai_image(session, ctx, ai_cfg):
                break
            ai_result = await generate_validated_ai_image(
                session,
                ai_prompt,
                output_dir,
                ctx,
                segment,
                min_relevance,
                ai_cfg,
                aspect_ratio,
                validation_brief,
                use_prompt_as_is=True,
                beat=ai_beat,
                visual_type=ai_visual_type,
            )
            await apply_ai_image_result(
                session,
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
    runway_limit = runway_cfg.max_clips_per_video
    if is_short_montage(ctx):
        runway_limit = max(runway_limit, runway_cfg.max_clips_per_short)
    if (
        missing_videos > 0
        and runway_cfg.enabled
        and session.runway_clips_used < runway_limit
        and (not is_derivation or derivation_allows_ai)
    ):
        runway_prompt = (
            f"{ctx.theme} — {segment.get('title', '')} — "
            f"{validation_brief.subject_entity} — {' '.join(keywords[:4])}"
        )
        for _ in range(missing_videos):
            if session.runway_clips_used >= runway_limit:
                break
            runway_item = await generate_runway_clip(
                session, runway_prompt, output_dir, runway_cfg, ctx
            )
            if runway_item:
                from agent.skills.media.asset_validation import validate_single_asset

                validated = await validate_single_asset(
                    session,
                    runway_item,
                    ctx=ctx,
                    segment=segment,
                    min_relevance=min_relevance,
                    output_dir=output_dir,
                    validation_brief=validation_brief,
                )
                if validated:
                    selected.append(validated)
                    session.runway_clips_used += 1

    if (
        len(selected) < assets_needed
        and ms_cfg.enable_ai_fallback
        and ai_cfg.enabled
        and (not is_derivation or derivation_allows_ai)
    ):
        remaining = assets_needed - len(selected)
        aspect_ratio = "9:16" if requires_vertical else "16:9"
        ai_prompt, ai_beat, ai_visual_type = await synthesize_segment_ai_prompt(
            session, ctx, segment, keywords,
            aspect_ratio=aspect_ratio,
            cache_dir=output_dir / "segment_prompt_cache",
        )
        for _ in range(min(remaining, ai_cfg.max_images_per_segment)):
            if len(selected) >= assets_needed:
                break
            if not await can_generate_ai_image(session, ctx, ai_cfg):
                break
            ai_result = await generate_validated_ai_image(
                session,
                ai_prompt,
                output_dir,
                ctx,
                segment,
                min_relevance,
                ai_cfg,
                aspect_ratio,
                validation_brief,
                use_prompt_as_is=True,
                beat=ai_beat,
                visual_type=ai_visual_type,
            )
            await apply_ai_image_result(
                session,
                ai_result,
                ctx=ctx,
                segment=segment,
                ai_prompt=ai_prompt,
                selected=selected,
                dev_attempts=dev_attempts,
                paid_attempts=paid_attempts,
            )

    if ms_cfg.enable_post_selection_audit and selected:
        selected = await audit_selected_media(
            session,
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

    pending: list[tuple[MediaAsset, Path | None, str, float | None]] = []
    for item in selected:
        is_video = item.get("asset_type") == "video"
        local_path = await download_asset(item, output_dir)
        rights = rights_fields(item)
        asset = MediaAsset(
            project_id=ctx.project_id,
            segment_order=order,
            source=item.get("source"),
            source_url=rights["source_url"],
            local_path=str(local_path) if local_path else item.get("local_generated"),
            license=rights["license"],
            attribution=rights["attribution"],
            author=rights["author"],
            requires_attribution=rights["requires_attribution"],
            asset_type="video" if is_video else "image",
            selected=True,
            relevance_score=item.get("_relevance_score"),
            relevance_reason=item.get("_relevance_reason"),
            library_status="selected",
            generation_prompt=item.get("title"),
            visual_type=None,
            iteration=media_iteration,
            clip_metadata=clip_metadata_for_media_item(item),
        )
        context = f"{segment.get('title', '')} — {item.get('title', '')}"
        pending.append((
            asset,
            local_path,
            context,
            float(item["duration_s"]) if item.get("duration_s") else None,
        ))

    await apply_perception_batch(session, ctx, pending)

    async with AsyncSessionFactory() as session_db:
        for asset, _, _, _ in pending:
            session_db.add(asset)
            assets.append(asset)
        await session_db.commit()

    logger.info(
        "Segment %d : %d médias (%d vidéos, %d images)",
        order,
        len(assets),
        sum(1 for a in assets if a.asset_type == "video"),
        sum(1 for a in assets if a.asset_type != "video"),
    )
    if not assets:
        title = segment.get("title", "")
        if order not in session.segment_media_gaps:
            session.media_gaps.append(
                MediaGap(
                    segment_order=order,
                    reason="no_media_above_threshold",
                    attempts=0,
                    prompt=(segment.get("narration_text") or title or "")[:500],
                )
            )
            session.segment_media_gaps.add(order)
        logger.warning(
            "Segment %d (« %s ») : aucun média retenu (seuil ≥ %d) — gap, scénario adapté",
            order, title, min_relevance,
        )
    return assets
