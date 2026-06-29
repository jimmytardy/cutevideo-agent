from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

from agent.core.media_validation import MediaValidationBrief
from agent.skills.media.rights_check import enrich_candidate, filter_publishable

if TYPE_CHECKING:
    from agent.core.orchestrator import PipelineContext
    from agent.core.visual_beats import VisualBeat
    from agent.skills.media.run_session import MediaRunSession

logger = logging.getLogger(__name__)

_GENERIC_KEYWORDS = frozenset({
    "nature", "animal", "animaux", "bird", "birds", "oiseau", "oiseaux",
    "histoire", "history", "science", "landscape", "paysage", "wildlife",
})

CallClaudeFn = Callable[..., Awaitable[str]]


def asset_key(item: dict) -> str:
    return str(item.get("local_generated") or item.get("url") or "")


def dedupe_and_filter(
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


def select_assets(
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


def build_anchored_queries(
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


def gate_publishable_candidates(
    candidates: list[dict],
) -> tuple[list[dict], list[dict]]:
    return filter_publishable(candidates)


def anchor_subject(session: MediaRunSession, ctx: PipelineContext) -> str:
    anchor = session.search_anchor
    if anchor is not None and anchor.is_usable:
        return anchor.anchor_en
    return ctx.theme


def anchored_keywords(session: MediaRunSession, keywords: list[str]) -> list[str]:
    anchor = session.search_anchor
    if anchor is None or not anchor.is_usable:
        return list(keywords)
    lead = list(anchor.terms_en)
    if anchor.anchor_en and anchor.anchor_en not in lead:
        lead.insert(0, anchor.anchor_en)
    seen = {k.lower() for k in lead}
    merged = list(lead)
    for kw in keywords:
        if kw and kw.lower() not in seen:
            seen.add(kw.lower())
            merged.append(kw)
    return merged


async def resolve_search_anchor(
    session: MediaRunSession,
    ctx: PipelineContext,
    validation_brief: MediaValidationBrief,
) -> None:
    from agent.skills.media_sources.ai.prompt_synthesizer import (
        SearchAnchor,
        translate_search_anchor,
    )

    if not validation_brief.subject_entity.strip():
        session.search_anchor = SearchAnchor()
        return
    cache_dir = Path(f"./tmp/{ctx.project_id}/search_anchor_cache")
    session.search_anchor = await translate_search_anchor(
        subject_entity=validation_brief.subject_entity,
        must_include=validation_brief.must_include,
        api_key=session.gemini_api_key or None,
        cache_dir=cache_dir,
    )


async def search_source(
    session: MediaRunSession,
    source: str,
    keywords: list[str],
    period: str,
    *,
    media_type: str = "image",
) -> list[dict]:
    from agent.skills.media_sources import (
        coverr,
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
        "coverr": coverr.search,
        "internet_archive": internet_archive.search,
        "nasa": nasa.search,
    }
    fn = source_map.get(source)
    if fn is None:
        return []
    orientation = session.search_orientation
    if source in ("pexels", "pixabay", "coverr"):
        raw = await fn(
            keywords, period, media_type=media_type, orientation=orientation  # type: ignore[arg-type]
        )
    else:
        raw = await fn(keywords, period, media_type=media_type)
    return [enrich_candidate(item) for item in raw]


async def llm_refined_keywords(
    segment: dict,
    video_subject: str,
    validation_brief: MediaValidationBrief,
    rejection_reasons: list[str],
    attempt: int,
    *,
    call_claude: CallClaudeFn,
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
        raw = await call_claude(prompt, model="claude-sonnet-4-5", max_tokens=256)
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1].rsplit("```", 1)[0]
        data = json.loads(raw)
        queries = data.get("queries", [])
        return [[str(k) for k in q] for q in queries if isinstance(q, list)]
    except Exception as e:
        logger.warning("LLM refined keywords échoué : %s", e)
        return []


async def llm_alternative_keywords(
    segment: dict,
    video_subject: str,
    *,
    call_claude: CallClaudeFn,
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
        raw = await call_claude(prompt, model="claude-sonnet-4-5", max_tokens=256)
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1].rsplit("```", 1)[0]
        data = json.loads(raw)
        queries = data.get("queries", [])
        return [[str(k) for k in q] for q in queries if isinstance(q, list)]
    except Exception as e:
        logger.warning("LLM keywords fallback échoué : %s", e)
        return []


async def search_with_fallback(
    session: MediaRunSession,
    sources: list[str],
    keywords: list[str],
    period: str,
    segment: dict,
    min_candidates: int,
    *,
    video_subject: str,
    media_type: str = "image",
    exclude_urls: set[str] | None = None,
    call_claude: CallClaudeFn | None = None,
) -> list[dict]:
    candidates: list[dict] = []
    fallback_sources = sources[:2]
    excluded = exclude_urls or set()

    for source in sources:
        try:
            found = await search_source(session, source, keywords, period, media_type=media_type)
            candidates.extend(found)
            if len(candidates) >= min_candidates * 2:
                break
        except Exception as e:
            logger.warning("Source %s (%s) échouée : %s", source, media_type, e)

    candidates = dedupe_and_filter(candidates, 0, exclude_urls=excluded)
    if len(candidates) >= min_candidates:
        return candidates

    anchored = build_anchored_queries(keywords, video_subject, segment.get("title", ""))
    for kw_list in anchored:
        for source in fallback_sources:
            try:
                found = await search_source(session, source, kw_list, "", media_type=media_type)
                candidates.extend(found)
            except Exception:
                pass
        candidates = dedupe_and_filter(candidates, 0, exclude_urls=excluded)
        if len(candidates) >= min_candidates:
            return candidates

    if call_claude is not None:
        alt_keywords = await llm_alternative_keywords(
            segment, video_subject, call_claude=call_claude
        )
        for kw_list in alt_keywords:
            for source in fallback_sources:
                try:
                    found = await search_source(session, source, kw_list, "", media_type=media_type)
                    candidates.extend(found)
                except Exception:
                    pass
            candidates = dedupe_and_filter(candidates, 0, exclude_urls=excluded)
            if len(candidates) >= min_candidates:
                break

    return candidates


async def search_segment_with_iterations(
    session: MediaRunSession,
    *,
    ctx: PipelineContext,
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
    call_claude: CallClaudeFn | None = None,
    filter_candidates: Callable[..., Awaitable[tuple[list[dict], list[dict]]]] | None = None,
) -> list[dict]:
    from agent.skills.media.asset_validation import filter_candidates_by_relevance

    filter_fn = filter_candidates or filter_candidates_by_relevance
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
            video_candidates = await search_with_fallback(
                session,
                effective_sources,
                current_keywords,
                period,
                segment,
                min_candidates,
                video_subject=anchor_subject(session, ctx),
                media_type="video",
                exclude_urls=rejected_urls,
                call_claude=call_claude,
            )
            video_candidates = dedupe_and_filter(
                video_candidates, ms_cfg.min_width_px, exclude_urls=rejected_urls
            )
            video_candidates, _ = gate_publishable_candidates(video_candidates)

        image_candidates = await search_with_fallback(
            session,
            effective_sources,
            current_keywords,
            period,
            segment,
            max(min_candidates, assets_needed),
            video_subject=anchor_subject(session, ctx),
            media_type="image",
            exclude_urls=rejected_urls,
            call_claude=call_claude,
        )
        image_candidates = dedupe_and_filter(
            image_candidates, ms_cfg.min_width_px, exclude_urls=rejected_urls
        )
        image_candidates, _ = gate_publishable_candidates(image_candidates)

        candidates = video_candidates + image_candidates
        total_raw_candidates += len(candidates)
        if not candidates:
            if call_claude is not None:
                refined = await llm_refined_keywords(
                    segment, ctx.theme, validation_brief, [], attempt, call_claude=call_claude
                )
                if refined:
                    current_keywords = refined[0]
            continue

        passing, rejected = await filter_fn(
            session,
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
        seen = {asset_key(p) for p in all_passing}
        for item in passing:
            key = asset_key(item)
            if key and key not in seen:
                seen.add(key)
                all_passing.append(item)

        if len(all_passing) >= passing_target:
            break

        if call_claude is not None:
            rejection_reasons = [
                f"{r.get('_rejection_category', 'off_topic')}: {r.get('_relevance_reason', '')}"
                for r in rejected[:8]
            ]
            refined_lists = await llm_refined_keywords(
                segment, ctx.theme, validation_brief, rejection_reasons, attempt,
                call_claude=call_claude,
            )
            if refined_lists:
                current_keywords = refined_lists[0]

    if validation_relaxed:
        session.relevance_log.append({
            "segment_order": order,
            "validation_relaxed": True,
        })

    session.relevance_log.append({
        "segment_order": order,
        "total_raw_candidates": total_raw_candidates,
        "passing_count": len(all_passing),
        "niche_risk": validation_brief.niche_risk,
    })
    return all_passing
