from __future__ import annotations

from dataclasses import dataclass

from agent.core.montage_plan import BeatClipPlan
from agent.skills.video.montage_decisions import (
    clip_duration_s,
    load_transition_config,
    total_visual_duration,
)


@dataclass(frozen=True)
class TimelineClipDraft:
    """Brouillon de clip avant enrichissement overlay/transitions."""

    beat_order: int
    source_beat_orders: list[int]
    asset_path: str
    asset_type: str
    timeline_start_s: float
    timeline_end_s: float
    source_trim_start_s: float = 0.0
    source_trim_end_s: float | None = None
    trim_reason: str = ""
    on_screen_text: str = ""
    visual_type: str = "documentary_photo"
    strip_source_audio: bool = True


def split_beat_duration(
    start_s: float,
    total_duration_s: float,
    *,
    max_shot_s: float,
) -> list[tuple[float, float]]:
    """Découpe une durée de beat en sous-plans <= max_shot_s."""
    if total_duration_s <= 0:
        return []
    if total_duration_s <= max_shot_s:
        return [(start_s, start_s + total_duration_s)]

    chunks: list[tuple[float, float]] = []
    cursor = start_s
    remaining = total_duration_s
    while remaining > 0.01:
        chunk = min(max(max_shot_s, 0.5), remaining)
        chunks.append((cursor, cursor + chunk))
        cursor += chunk
        remaining -= chunk
    return chunks


def expand_timeline_to_clip_drafts(
    entries: list[TimelineClipDraft],
    *,
    max_static_shot_s: float,
) -> list[TimelineClipDraft]:
    """Éclate les beats longs en sous-clips conservant le même visuel/texte."""
    expanded: list[TimelineClipDraft] = []
    beat_counter = 0
    for entry in entries:
        beat_duration = max(entry.timeline_end_s - entry.timeline_start_s, 0.5)
        sub_ranges = split_beat_duration(
            entry.timeline_start_s,
            beat_duration,
            max_shot_s=max_static_shot_s,
        )
        for sub_start, sub_end in sub_ranges:
            beat_counter += 1
            expanded.append(
                TimelineClipDraft(
                    beat_order=beat_counter,
                    source_beat_orders=list(entry.source_beat_orders),
                    asset_path=entry.asset_path,
                    asset_type=entry.asset_type,
                    timeline_start_s=sub_start,
                    timeline_end_s=sub_end,
                    source_trim_start_s=entry.source_trim_start_s,
                    source_trim_end_s=entry.source_trim_end_s,
                    trim_reason=entry.trim_reason,
                    on_screen_text=entry.on_screen_text,
                    visual_type=entry.visual_type,
                    strip_source_audio=entry.strip_source_audio,
                )
            )
    return expanded


def validate_visual_audio_alignment(
    clips: list[BeatClipPlan],
    audio_duration_s: float,
    *,
    tolerance_s: float = 0.5,
) -> None:
    """Lève si la durée visuelle totale diverge trop de l'audio."""
    trans_cfg = load_transition_config()
    durations = [clip_duration_s(c) for c in clips]
    visual_total = total_visual_duration(
        durations,
        trans_cfg.duration_s,
        trans_cfg.enabled and len(clips) > 1,
    )
    if abs(visual_total - audio_duration_s) > tolerance_s:
        raise RuntimeError(
            f"Désalignement montage : visuel {visual_total:.2f}s vs audio "
            f"{audio_duration_s:.2f}s (tolérance {tolerance_s}s)"
        )


def extend_last_clip_to_match_audio(
    clips: list[BeatClipPlan],
    audio_duration_s: float,
) -> list[BeatClipPlan]:
    """Allonge le dernier clip si la vidéo est légèrement plus courte que l'audio."""
    if not clips:
        return clips
    trans_cfg = load_transition_config()
    durations = [clip_duration_s(c) for c in clips]
    visual_total = total_visual_duration(
        durations,
        trans_cfg.duration_s,
        trans_cfg.enabled and len(clips) > 1,
    )
    delta = audio_duration_s - visual_total
    if delta <= 0.01:
        return clips
    last = clips[-1]
    updated = last.model_copy(
        update={"timeline_end_s": last.timeline_end_s + delta}
    )
    return [*clips[:-1], updated]
