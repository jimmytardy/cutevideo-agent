from __future__ import annotations

from agent.core.montage_plan import BeatClipPlan


def snap_time_to_nearest_beat(
    t: float,
    beats: list[float],
    *,
    tolerance_s: float,
) -> float:
    """Retourne t inchangé si aucun beat dans ±tolerance_s."""
    if not beats or tolerance_s <= 0:
        return t
    nearest = min(beats, key=lambda b: abs(b - t))
    if abs(nearest - t) <= tolerance_s:
        return nearest
    return t


def snap_clip_boundaries(
    clips: list[BeatClipPlan],
    beats: list[float],
    *,
    tolerance_s: float,
    audio_duration_s: float,
) -> list[BeatClipPlan]:
    """Snap les frontières internes au beat le plus proche (≤ tolérance)."""
    if len(clips) < 2 or not beats:
        return clips

    snapped: list[BeatClipPlan] = []
    for i, clip in enumerate(clips):
        if i == 0:
            snapped.append(clip)
            continue

        boundary = clip.timeline_start_s
        new_boundary = snap_time_to_nearest_beat(boundary, beats, tolerance_s=tolerance_s)
        new_boundary = max(0.0, min(new_boundary, audio_duration_s))

        prev = snapped[-1]
        if new_boundary <= prev.timeline_start_s + 0.1:
            snapped.append(clip)
            continue

        snapped[-1] = prev.model_copy(update={"timeline_end_s": new_boundary})
        snapped.append(
            clip.model_copy(
                update={
                    "timeline_start_s": new_boundary,
                    "timeline_end_s": max(new_boundary + 0.1, clip.timeline_end_s),
                }
            )
        )

    if snapped:
        last_orig = clips[-1]
        last = snapped[-1]
        if last.timeline_end_s != last_orig.timeline_end_s:
            snapped[-1] = last.model_copy(update={"timeline_end_s": last_orig.timeline_end_s})

    return snapped


def measure_beat_alignment(
    cut_times: list[float],
    beats: list[float],
    tolerance_s: float,
) -> float:
    """Ratio de cuts ayant un beat à ±tolerance_s."""
    if not cut_times:
        return 1.0
    if not beats:
        return 0.0
    aligned = sum(
        1
        for t in cut_times
        if any(abs(b - t) <= tolerance_s for b in beats)
    )
    return aligned / len(cut_times)


def assign_jl_cuts(
    clips: list[BeatClipPlan],
    jl_cfg: dict[str, float | bool],
    *,
    is_short: bool,
) -> list[BeatClipPlan]:
    """Assigne audio_lead_s / audio_trail_s en alternance (shorts, opt-in)."""
    if not is_short or not jl_cfg.get("enabled"):
        return clips
    if len(clips) < 2:
        return clips

    max_lead = float(jl_cfg.get("max_audio_lead_s", 0.3))
    max_trail = float(jl_cfg.get("max_audio_trail_s", 0.3))
    updated: list[BeatClipPlan] = []
    for i, clip in enumerate(clips):
        if i == 0 or i == len(clips) - 1:
            updated.append(clip)
            continue
        if i % 2 == 0:
            updated.append(clip.model_copy(update={"audio_lead_s": max_lead}))
        else:
            updated.append(clip.model_copy(update={"audio_trail_s": max_trail}))
    return updated
