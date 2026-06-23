from __future__ import annotations

from typing import Any

from agent.agents.hook_optimizer_agent import HOOK_OPTIMIZABLE_KEYS
from agent.agents.narrator_agent import segment_needs_voice
from agent.skills.media.progress import MediaProgressData
from agent.skills.pipeline_progress.models import AgentProgressData

RESEARCH_SECTION_KEYS: tuple[str, ...] = (
    "key_facts",
    "sources",
    "timeline",
    "visual_anchors",
    "common_misconceptions",
    "narrative_angles",
)
RESEARCH_SECTIONS_TOTAL = len(RESEARCH_SECTION_KEYS)


def build_progress(
    done: int,
    total: int,
    *,
    detail: str | None = None,
    segments_done: int | None = None,
    segments_total: int | None = None,
) -> AgentProgressData:
    if total <= 0:
        percent = 0
    else:
        percent = min(100, round(done / total * 100))
    return AgentProgressData(
        done=done,
        total=total,
        percent=percent,
        detail=detail,
        segments_done=segments_done,
        segments_total=segments_total,
    )


def compute_research_progress(brief: dict[str, Any] | None) -> AgentProgressData:
    if not brief:
        return build_progress(0, RESEARCH_SECTIONS_TOTAL, detail="0/6 sections")

    confidence = float(brief.get("confidence", 0.0) or 0.0)
    key_facts = brief.get("key_facts") or []
    if confidence == 0.0 and not key_facts:
        return build_progress(
            RESEARCH_SECTIONS_TOTAL,
            RESEARCH_SECTIONS_TOTAL,
            detail="Ignoré",
        )

    filled = sum(1 for key in RESEARCH_SECTION_KEYS if brief.get(key))
    return build_progress(
        filled,
        RESEARCH_SECTIONS_TOTAL,
        detail=f"{filled}/{RESEARCH_SECTIONS_TOTAL} sections",
    )


def compute_binary_progress(done: bool, *, detail: str | None = None) -> AgentProgressData:
    return build_progress(1 if done else 0, 1, detail=detail)


def compute_scenario_progress(segments: list[Any] | None) -> AgentProgressData:
    has_segments = bool(segments)
    count = len(segments or [])
    detail = f"{count} segments" if has_segments else None
    return build_progress(1 if has_segments else 0, 1, detail=detail)


def compute_outline_progress(outline: dict[str, Any] | None) -> AgentProgressData:
    segments = (outline or {}).get("segments") or []
    if not segments:
        return build_progress(0, 1)
    return build_progress(1, 1, detail=f"{len(segments)} segments plan")


def compute_hook_progress(hook_segment: dict[str, Any] | None) -> AgentProgressData:
    total = len(HOOK_OPTIMIZABLE_KEYS)
    if not hook_segment:
        return build_progress(0, total, detail=f"0/{total} champs")
    filled = sum(
        1 for key in HOOK_OPTIMIZABLE_KEYS if hook_segment.get(key) not in (None, "", [], {})
    )
    total = len(HOOK_OPTIMIZABLE_KEYS)
    return build_progress(filled, total, detail=f"{filled}/{total} champs")


def count_voice_segments(segments: list[Any] | None) -> int:
    return sum(1 for seg in (segments or []) if isinstance(seg, dict) and segment_needs_voice(seg))


def compute_narrator_progress(audio_count: int, voice_total: int) -> AgentProgressData:
    if voice_total <= 0:
        return build_progress(0, 0)
    return build_progress(
        min(audio_count, voice_total),
        voice_total,
        detail=f"{audio_count}/{voice_total} voix",
    )


def compute_montage_progress(plan_segment_count: int, scenario_segment_count: int) -> AgentProgressData:
    total = scenario_segment_count if scenario_segment_count > 0 else 0
    if total <= 0:
        return build_progress(0, 0)
    done = min(plan_segment_count, total)
    return build_progress(done, total, detail=f"{done}/{total} segments")


def compute_media_agent_progress(media: MediaProgressData) -> AgentProgressData:
    return build_progress(
        media.found,
        media.total,
        detail=f"{media.found}/{media.total} médias",
        segments_done=media.segments_done,
        segments_total=media.segments_total,
    )


def compute_short_editor_progress(short_video_count: int, expected_total: int) -> AgentProgressData:
    if expected_total <= 0:
        return build_progress(0, 0)
    done = min(short_video_count, expected_total)
    return build_progress(done, expected_total, detail=f"{done}/{expected_total} exports")
