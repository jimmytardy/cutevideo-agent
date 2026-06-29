from __future__ import annotations

import logging
from dataclasses import dataclass

from agent.core.montage_plan import ClipMetadata, ClipSegmentMeta

logger = logging.getLogger(__name__)

_MIN_WINDOW_S = 0.5


@dataclass(frozen=True)
class TrimSelection:
    start_s: float
    end_s: float
    reason: str


def pick_best_segment(segments: list[ClipSegmentMeta]) -> ClipSegmentMeta:
    """Retourne le segment au meilleur score."""
    return max(segments, key=lambda s: s.score)


def _window_around_peak(
    peak_s: float,
    target: float,
    source_duration_s: float,
    segment: ClipSegmentMeta,
) -> tuple[float, float] | None:
    """Construit une fenêtre de durée ``target`` centrée sur ``peak_s``."""
    start = peak_s - target / 2.0
    end = start + target

    if start < 0.0:
        start = 0.0
        end = start + target
    if end > source_duration_s:
        end = source_duration_s
        start = max(0.0, end - target)

    if peak_s < start:
        start = max(0.0, peak_s)
        end = min(source_duration_s, start + target)
    if peak_s > end:
        end = min(source_duration_s, peak_s)
        start = max(0.0, end - target)

    seg_start, seg_end = segment.start_s, segment.end_s
    if start < seg_start and peak_s >= seg_start:
        shift = seg_start - start
        start = seg_start
        end = min(source_duration_s, end + shift)
    if end > seg_end and peak_s <= seg_end:
        shift = end - seg_end
        end = seg_end
        start = max(0.0, start - shift)

    if end - start < _MIN_WINDOW_S:
        return None
    return start, end


def select_trim_window(
    *,
    source_duration_s: float,
    target_duration_s: float,
    phrase_anchor: str,
    visual_type: str,
    clip_metadata: ClipMetadata | None = None,
) -> TrimSelection:
    """Choisit une fenêtre de trim dans un clip source."""
    target = max(_MIN_WINDOW_S, min(target_duration_s, source_duration_s))
    if clip_metadata and clip_metadata.best_segments:
        best = pick_best_segment(clip_metadata.best_segments)
        seg_len = best.end_s - best.start_s
        if seg_len >= target * 0.5:
            peak = (
                best.peak_s
                if best.peak_s is not None
                else (best.start_s + best.end_s) / 2.0
            )
            window = _window_around_peak(peak, target, source_duration_s, best)
            if window is not None:
                start, end = window
                return TrimSelection(
                    start_s=start,
                    end_s=end,
                    reason=f"peak@{peak:.1f}s — {best.reason or 'best_segment from clip analysis'}",
                )

    if visual_type == "establishing_shot":
        start = 0.0
        end = min(target, source_duration_s)
        return TrimSelection(start, end, "establishing_shot — début du clip")

    if source_duration_s <= target + 0.01:
        return TrimSelection(0.0, source_duration_s, "clip entier plus court que le beat")

    start = max(0.0, (source_duration_s - target) / 2.0)
    end = min(source_duration_s, start + target)
    return TrimSelection(start, end, f"fenêtre centrée pour « {phrase_anchor[:40]} »")
