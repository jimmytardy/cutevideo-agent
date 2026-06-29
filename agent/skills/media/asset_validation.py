from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from agent.core.media_validation import MediaValidationBrief
from agent.core.visual_beats import VisualBeat, beat_narration_excerpt
from agent.skills.media.asset_resolver import select_assets
from agent.skills.media_sources.relevance_scorer import score_media_candidates

if TYPE_CHECKING:
    from agent.core.orchestrator import PipelineContext
    from agent.skills.media.run_session import MediaRunSession

logger = logging.getLogger(__name__)


async def filter_candidates_by_relevance(
    session: MediaRunSession,
    candidates: list[dict],
    *,
    ctx: PipelineContext,
    segment: dict,
    min_relevance: int,
    output_dir: Path,
    segment_order: int,
    validation_brief: MediaValidationBrief,
    attempt: int = 1,
    beat: VisualBeat | None = None,
) -> tuple[list[dict], list[dict]]:
    narration = (segment.get("narration_text") or "")[:500]
    if beat is not None:
        narration = beat_narration_excerpt(beat)

    scored = await score_media_candidates(
        candidates,
        video_subject=ctx.theme,
        channel_category=ctx.theme_category,
        segment_title=segment.get("title", ""),
        segment_narration=narration,
        api_key=session.gemini_api_key,
        cache_dir=output_dir / "scoring",
        validation_brief=validation_brief,
        segment_order=segment_order,
        beat=beat,
        scoring_models=session.scoring_models,
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
    session.relevance_log.append(log_entry)
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


async def validate_single_asset(
    session: MediaRunSession,
    item: dict,
    *,
    ctx: PipelineContext,
    segment: dict,
    min_relevance: int,
    output_dir: Path,
    validation_brief: MediaValidationBrief,
) -> dict | None:
    passing, _ = await filter_candidates_by_relevance(
        session,
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


async def audit_selected_media(
    session: MediaRunSession,
    selected: list[dict],
    *,
    ctx: PipelineContext,
    segment: dict,
    min_relevance: int,
    output_dir: Path,
    validation_brief: MediaValidationBrief,
    assets_needed: int,
    video_target: int,
) -> list[dict]:
    floor = ctx.channel_config.media_sources.forced_best_min_score
    audited: list[dict] = []
    for item in selected:
        if item.get("_relevance_validated"):
            audited.append(item)
            continue
        if item.get("_relevance_forced_fallback"):
            score = int(item.get("_relevance_score") or 0)
            if score >= floor:
                audited.append(item)
            else:
                logger.warning(
                    "Audit : visuel forced_best écarté (score %d < plancher %d)",
                    score, floor,
                )
            continue
        validated = await validate_single_asset(
            session,
            item,
            ctx=ctx,
            segment=segment,
            min_relevance=min_relevance,
            output_dir=output_dir,
            validation_brief=validation_brief,
        )
        if validated:
            audited.append(validated)
    return select_assets(audited, video_target, assets_needed)
