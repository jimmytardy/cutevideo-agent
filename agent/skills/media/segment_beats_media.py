from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING, Any

from agent.core.database import AsyncSessionFactory, MediaAsset
from agent.core.visual_beats import VisualBeat, beat_narration_excerpt, beats_to_dicts, parse_visual_beats
from agent.skills.media.beat_source_routing import resolve_beat_sources
from agent.skills.media.media_library import (
    LIBRARY_SELECTED,
    promote_to_pool,
    query_pool,
    try_reuse_for_beat,
    trim_pool,
)
from agent.skills.media_sources.ai.prompt_builder import build_visual_prompt
from agent.skills.media_sources.ai.prompt_synthesizer import synthesize_flux_subject

if TYPE_CHECKING:
    from agent.agents.media_agent import MediaAgent
    from agent.core.media_validation import MediaValidationBrief
    from agent.core.orchestrator import PipelineContext

logger = logging.getLogger(__name__)

_EXPLANATORY_TYPES = frozenset({
    "scientific_diagram",
    "infographic",
    "data_chart",
    "comparison",
    "cross_section",
    "timeline",
    "map",
    "quote_card",
    "statistic_highlight",
})


async def synthesize_beat_ai_prompt(
    agent: "MediaAgent",
    ctx: "PipelineContext",
    beat: VisualBeat,
    *,
    aspect_ratio: str,
    cache_dir: Any,
) -> str:
    """Brief FR du beat → sujet EN (Gemini) → prompt FLUX riche (sujet en tête + style bible).

    Chemin unique de construction de prompt IA, partagé par le rendu par-beat et le
    fallback segment, pour éviter la « salade de mots-clés ».
    """
    subject_en = await synthesize_flux_subject(
        visual_type=beat.visual_type,
        prompt_fr=beat.prompt,
        style_hint=beat.style_hint,
        phrase_anchor=beat.phrase_anchor,
        api_key=getattr(agent, "_gemini_api_key", "") or None,
        cache_dir=cache_dir,
    )
    return build_visual_prompt(
        beat.visual_type,
        subject_en,
        style_hint=beat.style_hint,
        theme_category=ctx.theme_category,
        editorial_tone=ctx.channel_config.editorial_tone,
        aspect_ratio=aspect_ratio,
        style_block=getattr(ctx, "visual_style_block", "") or "",
    )


async def synthesize_segment_ai_prompt(
    agent: "MediaAgent",
    ctx: "PipelineContext",
    segment: dict[str, Any],
    keywords: list[str],
    *,
    aspect_ratio: str,
    cache_dir: Any,
) -> tuple[str, VisualBeat | None, str]:
    """Prompt IA pour un fallback au niveau SEGMENT (pas de beat ciblé).

    Réutilise le premier beat du segment si disponible (prompt riche du beat_planner),
    sinon construit un brief FR à partir du titre + narration + mots-clés et le synthétise.
    Retourne (prompt, beat|None, visual_type).
    """
    beats = parse_visual_beats(segment)
    if beats:
        beat = beats[0]
        prompt = await synthesize_beat_ai_prompt(
            agent, ctx, beat, aspect_ratio=aspect_ratio, cache_dir=cache_dir
        )
        return prompt, beat, beat.visual_type

    subject_fr = " — ".join(
        part
        for part in (
            str(segment.get("title") or ""),
            (str(segment.get("narration_text") or ""))[:200],
            ", ".join(keywords[:4]),
        )
        if part
    )
    subject_en = await synthesize_flux_subject(
        visual_type="documentary_photo",
        prompt_fr=subject_fr,
        style_hint="",
        phrase_anchor=str(segment.get("title") or ""),
        api_key=getattr(agent, "_gemini_api_key", "") or None,
        cache_dir=cache_dir,
    )
    prompt = build_visual_prompt(
        "documentary_photo",
        subject_en,
        theme_category=ctx.theme_category,
        editorial_tone=ctx.channel_config.editorial_tone,
        aspect_ratio=aspect_ratio,
        style_block=getattr(ctx, "visual_style_block", "") or "",
    )
    return prompt, None, "documentary_photo"


def _beat_video_target(beat: VisualBeat, ms_cfg: Any) -> int:
    """1 clip stock si prefer_video et le beat se prête à de la vidéo documentaire."""
    if not ms_cfg.prefer_video:
        return 0
    from agent.skills.media_sources.ai.prompt_builder import is_diagram_visual_type

    if is_diagram_visual_type(beat.visual_type) or beat.visual_type in _EXPLANATORY_TYPES:
        return 0
    return 1


async def process_segment_beats(
    agent: MediaAgent,
    ctx: PipelineContext,
    segment: dict[str, Any],
    sources: list[str],
    ms_cfg: Any,
    ai_cfg: Any,
    validation_brief: MediaValidationBrief,
    pool_assets: list[MediaAsset],
) -> list[MediaAsset]:
    from pathlib import Path

    from agent.skills.media.scenario_media_gap import ai_fallback_attempt_config

    beats = parse_visual_beats(segment)
    if not beats:
        return []

    order = int(segment.get("order", 0))
    keywords = segment.get("search_keywords", [])
    lib_cfg = ctx.channel_config.media_library
    is_derivation = getattr(ctx, "derivation_short_index", None) is not None
    aspect_ratio = (
        "9:16"
        if ctx.channel_config.production_mode == "shorts_only" or is_derivation
        else "16:9"
    )
    if is_derivation:
        idx = ctx.derivation_short_index or 0
        output_dir = Path(f"./tmp/{ctx.project_id}/shorts/{idx:02d}/media/segment_{order:02d}")
    else:
        output_dir = Path(f"./tmp/{ctx.project_id}/media/segment_{order:02d}")
    output_dir.mkdir(parents=True, exist_ok=True)
    _, dev_attempts, paid_attempts = ai_fallback_attempt_config()

    assets: list[MediaAsset] = []
    used_pool_ids: set[str] = set()

    for beat in beats:
        asset: MediaAsset | None = None
        min_relevance = validation_brief.min_score_for_beat(order, beat)

        if lib_cfg.enabled and pool_assets:
            available = [a for a in pool_assets if str(a.id) not in used_pool_ids]
            if not getattr(ctx, "skip_media_pool_reuse", False):
                reused, score = await try_reuse_for_beat(
                    beat=beat,
                    segment=segment,
                    pool_assets=available,
                    validation_brief=validation_brief,
                    video_subject=ctx.theme,
                    channel_category=ctx.theme_category,
                    min_score=lib_cfg.reuse_min_score,
                    api_key=getattr(agent, "_gemini_api_key", "") or "",
                    output_dir=output_dir,
                    segment_order=order,
                )
                if reused:
                    asset = reused
                    used_pool_ids.add(str(reused.id))
                    assets.append(asset)
                    continue
            else:
                logger.info("Pool reuse désactivé (critique visuelle) — beat %d", beat.order)

        beat_keywords = agent._anchored_keywords(_beat_keywords(beat, keywords))
        video_target = _beat_video_target(beat, ms_cfg)
        allows_search = not is_derivation or getattr(ctx, "short_derivation_mode", None) != "reuse_pool_only"
        allows_ai = not is_derivation or getattr(ctx, "short_derivation_mode", None) == "full"
        source_plan = resolve_beat_sources(beat, segment, sources)
        agent._relevance_log.append({
            "segment_order": order,
            "beat_order": beat.order,
            "visual_type": beat.visual_type,
            "routing_reason": source_plan.routing_reason,
            "effective_sources": source_plan.sources,
            "skip_stock": source_plan.skip_stock,
        })
        beat_sources = list(source_plan.sources)
        if is_derivation:
            beat_sources = [s for s in beat_sources if s != "ai"]
        candidates: list[dict] = []
        if allows_search and not source_plan.skip_stock:
            candidates = await agent._search_segment_with_iterations(
                ctx=ctx,
                segment={**segment, "search_keywords": beat_keywords},
                sources=sources,
                ms_cfg=ms_cfg,
                keywords=beat_keywords,
                period=segment.get("historical_period", ""),
                effective_sources=beat_sources,
                assets_needed=1,
                video_target=video_target,
                min_candidates=2,
                min_relevance=min_relevance,
                output_dir=output_dir / f"beat_{beat.order:02d}",
                validation_brief=validation_brief,
                order=order,
                beat=beat,
            )
        selected = agent._select_assets(candidates, video_target, 1)

        if not selected and ms_cfg.enable_ai_fallback and ai_cfg.enabled and allows_ai:
            beat_dir = output_dir / f"beat_{beat.order:02d}"
            ai_prompt = await synthesize_beat_ai_prompt(
                agent, ctx, beat, aspect_ratio=aspect_ratio,
                cache_dir=beat_dir / "prompt_cache",
            )
            if await agent._can_generate_ai_image(ctx, ai_cfg):
                ai_result = await agent._generate_validated_ai_image(
                    ai_prompt,
                    beat_dir,
                    ctx,
                    {**segment, "narration_text": beat_narration_excerpt(beat)},
                    min_relevance,
                    ai_cfg,
                    aspect_ratio,
                    validation_brief,
                    use_prompt_as_is=True,
                    beat=beat,
                    visual_type=beat.visual_type,
                )
                pending: list[dict] = []
                await agent._apply_ai_image_result(
                    ai_result,
                    ctx=ctx,
                    segment=segment,
                    ai_prompt=ai_prompt,
                    selected=pending,
                    dev_attempts=dev_attempts,
                    paid_attempts=paid_attempts,
                )
                selected = pending

        if selected:
            item = selected[0]
            asset = await agent._persist_beat_asset(
                ctx=ctx,
                item=item,
                segment_order=order,
                beat=beat,
                output_dir=output_dir / f"beat_{beat.order:02d}",
                generation_prompt=item.get("_generation_prompt") or beat.prompt,
            )
            assets.append(asset)
            for extra in selected[1:]:
                await agent._persist_pool_candidate(
                    ctx, extra, order, beat, output_dir, lib_cfg.pool_min_score
                )
        else:
            logger.warning("Beat %d segment %d : aucun média trouvé", beat.order, order)
            agent._segment_media_gaps.add(order)

    if lib_cfg.enabled:
        await trim_pool(ctx.project_id, lib_cfg.max_pool_size_per_project)

    return assets


def _beat_keywords(beat: VisualBeat, segment_keywords: list[str]) -> list[str]:
    from agent.core.prompt_safety import sanitize_search_terms

    extra = beat.prompt.split()[:4]
    combined = list(segment_keywords[:2]) + extra
    seen: set[str] = set()
    out: list[str] = []
    for kw in combined:
        k = kw.strip()
        if k and k.lower() not in seen:
            seen.add(k.lower())
            out.append(k)
    # Chokepoint final avant requête média externe : neutralise la syntaxe de requête
    # (beat.prompt est aussi du texte LLM, donc non fiable).
    return sanitize_search_terms(out[:6] or segment_keywords[:4])


def ensure_visual_beats_on_segments(
    segments: list[dict[str, Any]],
    *,
    is_short: bool,
    min_beats: int,
    max_beats: int,
    editorial_tone: str,
    theme_category: str,
    vb_config: Any | None = None,
) -> list[dict[str, Any]]:
    from agent.core.visual_beats import validate_beats_against_narration

    updated: list[dict[str, Any]] = []
    for seg in segments:
        seg = dict(seg)
        has_voice = seg.get("needs_voice", True) is not False and bool(
            (seg.get("narration_text") or "").strip()
        )
        if has_voice:
            seg.pop("visual_beats", None)
            updated.append(seg)
            continue
        errors = validate_beats_against_narration(
            seg,
            vb_config=vb_config,
            is_short=is_short,
        )
        if not errors:
            updated.append(seg)
            continue
        seg["visual_beats"] = _fallback_beats_from_narration(
            seg,
            is_short=is_short,
            min_beats=min_beats,
            max_beats=max_beats,
            editorial_tone=editorial_tone,
            theme_category=theme_category,
            vb_config=vb_config,
        )
        updated.append(seg)
    return updated


def _fallback_beats_from_narration(
    segment: dict[str, Any],
    *,
    is_short: bool,
    min_beats: int,
    max_beats: int,
    editorial_tone: str,
    theme_category: str,
    vb_config: Any | None = None,
) -> list[dict[str, Any]]:
    from agent.core.visual_beats import suggest_types_for_tone
    from agent.skills.media_sources.ai.prompt_builder import is_diagram_visual_type

    min_diagram = 4.0 if is_short else 6.0
    if vb_config is not None:
        min_diagram = (
            float(getattr(vb_config, "min_diagram_duration_short_s", 4.0))
            if is_short
            else float(getattr(vb_config, "min_diagram_duration_s", 6.0))
        )

    narration = (segment.get("narration_text") or "").strip()
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", narration) if s.strip()]
    if not sentences:
        sentences = [narration[:120]] if narration else ["segment"]
    target = min(max_beats, max(min_beats, len(sentences) if is_short else len(sentences)))
    sentences = sentences[:target]
    suggested = suggest_types_for_tone(editorial_tone, theme_category)
    default_types = ["documentary_photo", "scientific_diagram", "infographic", "comparison"]
    type_cycle = suggested or default_types

    beats: list[dict[str, Any]] = []
    for i, sentence in enumerate(sentences):
        vtype = type_cycle[i % len(type_cycle)]
        if i > 0 and vtype == "documentary_photo" and i % 2 == 1:
            vtype = "scientific_diagram"
        label_words = [w for w in sentence.split() if len(w) > 3][:2]
        label_text = " ".join(label_words)[:40] or sentence[:40]
        beat: dict[str, Any] = {
            "order": i + 1,
            "phrase_anchor": sentence[:80],
            "visual_type": vtype,
            "prompt": f"{segment.get('title', '')} — {sentence[:120]}",
            "style_hint": "",
            "on_screen_text": "",
        }
        if is_diagram_visual_type(vtype):
            beat["diagram_labels"] = [{"text": label_text, "role": "element"}]
            beat["duration_hint_s"] = min_diagram
        elif i == 0:
            beat["on_screen_text"] = segment.get("on_screen_text", "") or label_text
        beats.append(beat)
    return beats
