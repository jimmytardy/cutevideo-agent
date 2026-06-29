from __future__ import annotations

from typing import Any

from agent.core.content_plan_models import DailyContentPlan, VideoTopicPlan
from agent.core.editorial_formats import EditorialFormatDefinition


def pick_available_format_ids(
    bank: list[EditorialFormatDefinition],
    recent_ids: list[str],
    k: int,
) -> list[str]:
    """IDs de formats autorisés (hors fenêtre K). Fallback si banque trop petite."""
    if not bank:
        return []
    blocked = set(recent_ids[:k])
    available = [f.id for f in bank if f.id not in blocked]
    if available:
        return available
    for fmt_id in reversed(recent_ids):
        if fmt_id in {f.id for f in bank}:
            return [fmt_id]
    return [bank[0].id]


def pick_intro_outro_variants(
    fmt: EditorialFormatDefinition,
    recent_intro: list[str],
    recent_outro: list[str],
) -> tuple[str, str]:
    """Choisit intro/outro non répétés récemment."""
    intro = _pick_variant(fmt.intro_variants, recent_intro)
    outro = _pick_variant(fmt.outro_variants, recent_outro)
    return intro, outro


def _pick_variant(variants: list[str], recent: list[str]) -> str:
    if not variants:
        return ""
    blocked = set(recent[-3:])
    for v in variants:
        if v not in blocked:
            return v
    return variants[len(recent) % len(variants)]


def assign_formats_to_long_topics(
    topics: list[VideoTopicPlan],
    bank: list[EditorialFormatDefinition],
    format_history: list[str],
    intro_history: list[str],
    outro_history: list[str],
    *,
    k: int = 3,
) -> list[VideoTopicPlan]:
    """Assigne editorial_format_id + variants à chaque long, avec rotation."""
    if not topics or not bank:
        return topics

    bank_by_id = {f.id: f for f in bank}
    recent_ids = list(format_history)
    recent_intro = list(intro_history)
    recent_outro = list(outro_history)
    updated: list[VideoTopicPlan] = []

    for topic in topics:
        available = pick_available_format_ids(bank, recent_ids, k)
        chosen_id = topic.editorial_format_id if topic.editorial_format_id in bank_by_id else ""
        if not chosen_id:
            idx = len(updated) % len(available) if available else 0
            chosen_id = available[idx] if available else bank[0].id
        elif chosen_id not in available and available:
            chosen_id = available[len(updated) % len(available)]

        fmt = bank_by_id.get(chosen_id, bank[0])
        intro, outro = pick_intro_outro_variants(fmt, recent_intro, recent_outro)

        updated_topic = topic.model_copy(
            update={
                "editorial_format_id": fmt.id,
                "narrative_format": fmt.label,
                "intro_variant": intro,
                "outro_variant": outro,
            }
        )
        updated.append(updated_topic)
        recent_ids.insert(0, fmt.id)
        if intro:
            recent_intro.insert(0, intro)
        if outro:
            recent_outro.insert(0, outro)

    return updated


def apply_format_rotation_to_plan(
    plan: DailyContentPlan,
    bank: list[EditorialFormatDefinition],
    format_history: list[str],
    intro_history: list[str],
    outro_history: list[str],
    *,
    k: int = 3,
) -> DailyContentPlan:
    """Applique la rotation aux longs du plan (shorts héritent du parent si dérivés)."""
    longs = assign_formats_to_long_topics(
        plan.long_videos,
        bank,
        format_history,
        intro_history,
        outro_history,
        k=k,
    )
    long_by_index = {i: lv for i, lv in enumerate(longs)}

    updated_shorts: list[VideoTopicPlan] = []
    for short in plan.short_videos:
        parent_idx = short.parent_long_index
        if parent_idx is not None and parent_idx in long_by_index:
            parent = long_by_index[parent_idx]
            updated_shorts.append(
                short.model_copy(
                    update={
                        "editorial_format_id": parent.editorial_format_id,
                        "narrative_format": parent.narrative_format,
                        "intro_variant": parent.intro_variant,
                        "outro_variant": parent.outro_variant,
                    }
                )
            )
        else:
            updated_shorts.append(short)

    return plan.model_copy(update={"long_videos": longs, "short_videos": updated_shorts})


def extract_format_histories(
    history_rows: list[dict[str, Any]],
) -> tuple[list[str], list[str], list[str]]:
    """Extrait format_id, intro, outro depuis les lignes d'historique projet."""
    format_ids: list[str] = []
    intros: list[str] = []
    outros: list[str] = []
    for row in history_rows:
        plan = row.get("content_plan") or {}
        if not isinstance(plan, dict):
            continue
        fmt_id = str(plan.get("editorial_format_id") or plan.get("narrative_format") or "").strip()
        if fmt_id:
            format_ids.append(fmt_id)
        intro = str(plan.get("intro_variant") or "").strip()
        if intro:
            intros.append(intro)
        outro = str(plan.get("outro_variant") or "").strip()
        if outro:
            outros.append(outro)
    return format_ids, intros, outros
