from __future__ import annotations

import json
import logging
import uuid
from typing import Any

from agent.core.config import load_agent_config
from agent.core.database import AsyncSessionFactory, Scenario
from agent.core.json_parse import parse_json_text
from agent.core.llm_config import resolve_max_tokens
from agent.core.scenario_integrity import validate_segment_count_preserved
from agent.skills.media.ai_image_result import MediaGap

logger = logging.getLogger(__name__)

ADAPT_SYSTEM = """Tu adaptes un scénario vidéo lorsque certaines images IA n'ont pas pu être générées.

Pour chaque segment concerné :
- Réécris narration_text pour ne plus exiger un visuel précis impossible à produire
- Renforce on_screen_text pour compenser l'absence d'image
- Ajoute "visual_optional": true
- Conserve order, duration_s, delivery_style et les autres champs inchangés sauf si nécessaire

Retourne UNIQUEMENT du JSON valide avec les segments adaptés (pas besoin de renvoyer les autres)."""

ADAPT_PROMPT = """Sujet : {theme}

Segments sans visuel disponible (génération IA impossible) :
{gaps_text}

SEGMENTS À ADAPTER (JSON complet de chaque segment concerné) :
{gap_segments_json}

Adapte uniquement ces segments. Ne renvoie pas les autres segments.

Retourne :
{{
  "segments": [ ... uniquement les segments adaptés, avec leur champ "order" ... ],
  "total_duration_s": {total_duration_s}
}}"""


def _fallback_adapt_segments(
    segments: list[dict[str, Any]],
    gap_orders: set[int],
) -> list[dict[str, Any]]:
    """Adaptation locale minimale si le LLM renvoie un JSON invalide ou tronqué."""
    adapted: list[dict[str, Any]] = []
    for seg in segments:
        if not isinstance(seg, dict):
            adapted.append(seg)
            continue
        order = int(seg.get("order", 0))
        if order not in gap_orders:
            adapted.append(dict(seg))
            continue
        updated = dict(seg)
        updated["visual_optional"] = True
        if not (updated.get("on_screen_text") or "").strip():
            updated["on_screen_text"] = str(updated.get("title", ""))[:80]
        adapted.append(updated)
    return adapted


def _merge_adapted_segments(
    segments: list[dict[str, Any]],
    adapted_segments: list[dict[str, Any]],
    gap_orders: set[int],
) -> list[dict[str, Any]]:
    by_order = {
        int(seg["order"]): dict(seg)
        for seg in adapted_segments
        if isinstance(seg, dict) and seg.get("order") is not None
    }
    merged: list[dict[str, Any]] = []
    for seg in segments:
        if not isinstance(seg, dict):
            merged.append(seg)
            continue
        order = int(seg.get("order", 0))
        if order in gap_orders and order in by_order:
            merged.append(by_order[order])
        else:
            merged.append(dict(seg))
    return merged


async def adapt_scenario_for_media_gaps(
    scenario: Scenario,
    gaps: list[MediaGap],
    *,
    theme: str,
    user_id: uuid.UUID | None = None,
) -> tuple[Scenario, list[int]]:
    """Réécrit le scénario pour les segments sans image IA possible."""
    if not gaps:
        return scenario, []

    segments = list(scenario.segments or [])
    gap_orders = {g.segment_order for g in gaps}
    gaps_text = "\n".join(
        f"- Segment {g.segment_order} : {g.reason} ({g.attempts} tentatives) — prompt : {g.prompt[:120]}"
        for g in gaps
    )

    gap_segments = [
        seg for seg in segments if isinstance(seg, dict) and int(seg.get("order", 0)) in gap_orders
    ]
    prompt = ADAPT_PROMPT.format(
        theme=theme,
        gaps_text=gaps_text,
        gap_segments_json=json.dumps(gap_segments, ensure_ascii=False, indent=2),
        total_duration_s=scenario.total_duration_s or 0,
    )

    from agent.core.database import User
    from agent.core.llm_resolver import call_llm

    async with AsyncSessionFactory() as session:
        user = await session.get(User, user_id) if user_id else None
        raw = await call_llm(
            session,
            user,
            "scenario_media_gap",
            prompt,
            system=ADAPT_SYSTEM,
            max_tokens=resolve_max_tokens("scenario_agent"),
            model_override="claude-sonnet-4-5",
        )
    try:
        data = parse_json_text(raw, "scenario_media_gap", repair_fn=None)
    except (json.JSONDecodeError, ValueError) as exc:
        logger.warning(
            "Adaptation scénario LLM JSON invalide (%s) — fallback local segments %s",
            exc,
            sorted(gap_orders),
        )
        data = {"segments": _fallback_adapt_segments(segments, gap_orders)}
    adapted_segments = data.get("segments")
    if not isinstance(adapted_segments, list) or not adapted_segments:
        logger.warning(
            "Adaptation scénario LLM sans segments — fallback local segments %s",
            sorted(gap_orders),
        )
        new_segments = _fallback_adapt_segments(segments, gap_orders)
    else:
        new_segments = _merge_adapted_segments(segments, adapted_segments, gap_orders)

    validate_segment_count_preserved(
        segments,
        new_segments,
        context="scenario_media_gap",
    )

    for seg in new_segments:
        order = seg.get("order", 0)
        if order in gap_orders:
            seg["visual_optional"] = True
            if not (seg.get("on_screen_text") or "").strip():
                seg["on_screen_text"] = str(seg.get("title", ""))[:80]

    async with AsyncSessionFactory() as session:
        db_scenario = await session.get(Scenario, scenario.id)
        if db_scenario is None:
            return scenario, []
        db_scenario.segments = new_segments
        if data.get("total_duration_s") is not None:
            db_scenario.total_duration_s = int(data["total_duration_s"])
        await session.commit()
        await session.refresh(db_scenario)

    adapted_orders = sorted(gap_orders)
    logger.info(
        "Scénario adapté pour %d gap(s) média : segments %s",
        len(adapted_orders),
        adapted_orders,
    )
    return db_scenario, adapted_orders


def ai_fallback_attempt_config() -> tuple[str, int, int]:
    cfg = load_agent_config().get("media_sources", {}).get("ai_fallback", {})
    dev_plan = str(cfg.get("dev_plan", "flux_2_dev"))
    dev_attempts = int(cfg.get("dev_validation_attempts", 3))
    paid_attempts = int(cfg.get("paid_validation_attempts", 3))
    return dev_plan, dev_attempts, paid_attempts
