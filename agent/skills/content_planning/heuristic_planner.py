from __future__ import annotations

from datetime import date
from typing import Any

from rapidfuzz import fuzz

from typing import Any

from agent.core.content_plan_models import DailyContentPlan, ThemeAnalysis, VideoTopicPlan

SIMILARITY_THRESHOLD = 85


def _history_subjects(history: list[dict[str, Any]]) -> list[str]:
    subjects: list[str] = []
    for item in history:
        for key in ("subject", "theme", "title", "provisional_title"):
            val = item.get(key)
            if val and str(val).strip():
                subjects.append(str(val).strip())
    return subjects


def _is_too_similar(candidate: str, existing: list[str]) -> bool:
    if not candidate.strip():
        return True
    for subj in existing:
        if fuzz.token_set_ratio(candidate, subj) >= SIMILARITY_THRESHOLD:
            return True
    return False


def find_similar_in_history(
    candidate: str,
    history: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Return history entries whose any text field is too similar to candidate."""
    if not candidate.strip():
        return []
    results: list[dict[str, Any]] = []
    for item in history:
        for key in ("subject", "theme", "title", "provisional_title"):
            val = item.get(key)
            if val and fuzz.token_set_ratio(candidate, str(val).strip()) >= SIMILARITY_THRESHOLD:
                results.append({
                    "title": item.get("title") or item.get("provisional_title"),
                    "theme": item.get("theme"),
                    "created_at": item.get("created_at"),
                })
                break
    return results


def _pick_evergreen_topics(
    evergreen: list[str],
    count: int,
    used_subjects: list[str],
) -> list[str]:
    picked: list[str] = []
    pool = list(evergreen)
    idx = 0
    while len(picked) < count and pool:
        topic = pool[idx % len(pool)]
        idx += 1
        subject = f"{topic} — exploration documentaire"
        if not _is_too_similar(subject, used_subjects + picked):
            picked.append(subject)
        if idx > len(pool) * 3:
            picked.append(f"Sujet complémentaire {len(picked) + 1}")
            break
    while len(picked) < count:
        picked.append(f"Approfondissement thématique {len(picked) + 1}")
    return picked[:count]


def build_heuristic_plan(
    channel: Any,
    *,
    production_date: date,
    target_publish_date: date,
    long_count: int,
    short_count: int,
    default_long_s: int,
    default_short_s: int,
    history: list[dict[str, Any]],
    evergreen: list[str],
) -> DailyContentPlan:
    """Plan éditorial quotidien sans LLM."""
    used = _history_subjects(history)
    long_subjects = _pick_evergreen_topics(evergreen, long_count, used)
    used.extend(long_subjects)

    long_videos: list[VideoTopicPlan] = []
    for i, subject in enumerate(long_subjects):
        title = subject.split(" — ")[0][:70]
        long_videos.append(
            VideoTopicPlan(
                priority=i + 1,
                format="long",
                provisional_title=title,
                angle="Exploration du thème de la chaîne.",
                narrative_format="récit",
                estimated_duration_s=default_long_s,
                sub_theme=channel.theme_category,
                main_entities=[],
                seo_keywords=[channel.theme_category, channel.slug],
                subject=subject,
                parent_long_index=None,
            )
        )

    short_videos: list[VideoTopicPlan] = []
    for j in range(short_count):
        parent_idx = j % max(len(long_videos), 1)
        parent_subject = long_videos[parent_idx].subject if long_videos else channel.theme_category
        short_subject = f"Angle court : {parent_subject[:80]}"
        short_videos.append(
            VideoTopicPlan(
                priority=j + 1,
                format="short_derived",
                provisional_title=f"Short — {parent_subject[:50]}",
                angle="Extrait accrocheur du long du jour.",
                narrative_format="anecdote",
                estimated_duration_s=default_short_s,
                sub_theme=channel.theme_category,
                main_entities=[],
                seo_keywords=[channel.theme_category],
                subject=short_subject,
                parent_long_index=parent_idx,
            )
        )

    theme_analysis = ThemeAnalysis(
        sub_themes=[channel.theme_category],
        narrative_formats=["récit", "portrait"],
        central_figures=[],
        good_subject_criteria=["Pertinence niche", "Pas de doublon récent"],
    )

    return DailyContentPlan(
        plan_date=target_publish_date.isoformat(),
        production_date=production_date.isoformat(),
        target_publish_date=target_publish_date.isoformat(),
        channel_slug=channel.slug,
        theme_category=channel.theme_category,
        long_count=long_count,
        short_count=short_count,
        theme_analysis=theme_analysis,
        long_videos=long_videos,
        short_videos=short_videos,
        selection_rationale=(
            "Plan heuristique (evergreen + déduplication rapidfuzz), sans appel LLM."
        ),
        evergreen_fallback_used=True,
    )
