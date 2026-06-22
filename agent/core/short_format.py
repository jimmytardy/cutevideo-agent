"""Helpers partagés pour la détection short, le format 9:16 et le plafond de durée."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from agent.core.channel_config import ChannelRuntimeConfig
    from agent.core.orchestrator import PipelineContext

SHORT_DURATION_TOLERANCE_S = 5.0


def effective_short_max_duration_s(
    target_duration_seconds: int | None,
    channel_config: "ChannelRuntimeConfig",
) -> int:
    """Plafond short = min(cible projet, max configuré sur la chaîne)."""
    target = target_duration_seconds or channel_config.short_duration_s
    return min(int(target), int(channel_config.max_short_duration_s))


def clamp_short_total_duration(
    value: int | None,
    *,
    min_duration_s: int,
    max_duration_s: int,
    fallback: int,
) -> int:
    return min(max_duration_s, max(min_duration_s, int(value or fallback)))


def rescale_segment_durations(
    segments: list[dict[str, Any]],
    *,
    max_total_s: int,
) -> list[dict[str, Any]]:
    """Répartit proportionnellement les duration_s si la somme dépasse max_total_s."""
    if not segments:
        return segments
    total = sum(int(seg.get("duration_s") or 0) for seg in segments)
    if total <= 0 or total <= max_total_s:
        return segments
    ratio = max_total_s / total
    scaled: list[dict[str, Any]] = []
    remaining = max_total_s
    for i, seg in enumerate(segments):
        if i == len(segments) - 1:
            dur = max(1, remaining)
        else:
            dur = max(1, int(round(int(seg.get("duration_s") or 0) * ratio)))
            remaining -= dur
        updated = dict(seg)
        updated["duration_s"] = dur
        scaled.append(updated)
    return scaled


def clamp_short_scenario_payload(
    data: dict[str, Any],
    *,
    target_duration_seconds: int | None,
    channel_config: "ChannelRuntimeConfig",
) -> dict[str, Any]:
    """Clamp total_duration_s et rescale les segments pour un short."""
    effective_max = effective_short_max_duration_s(target_duration_seconds, channel_config)
    min_d = channel_config.min_short_duration_s
    total = clamp_short_total_duration(
        data.get("total_duration_s"),
        min_duration_s=min_d,
        max_duration_s=effective_max,
        fallback=effective_max,
    )
    segments = rescale_segment_durations(
        list(data.get("segments") or []),
        max_total_s=total,
    )
    return {**data, "total_duration_s": total, "segments": segments}


def requires_vertical_output(ctx: "PipelineContext") -> bool:
    """True si la sortie vidéo doit être 9:16 (short autonome ou dérivé natif)."""
    return bool(ctx.is_short_project or ctx.derivation_short_index is not None)


def exceeds_short_duration_limit(
    duration_s: float,
    *,
    target_duration_seconds: int | None,
    channel_config: "ChannelRuntimeConfig",
    tolerance_s: float = SHORT_DURATION_TOLERANCE_S,
) -> bool:
    effective_max = effective_short_max_duration_s(target_duration_seconds, channel_config)
    return duration_s > effective_max + tolerance_s
