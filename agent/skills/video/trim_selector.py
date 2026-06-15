from __future__ import annotations

import logging
from dataclasses import dataclass

from agent.core.montage_plan import ClipMetadata, ClipSegmentMeta

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TrimSelection:
    start_s: float
    end_s: float
    reason: str


def select_trim_window(
    *,
    source_duration_s: float,
    target_duration_s: float,
    phrase_anchor: str,
    visual_type: str,
    clip_metadata: ClipMetadata | None = None,
) -> TrimSelection:
    """Choisit une fenêtre de trim dans un clip source."""
    target = max(0.5, min(target_duration_s, source_duration_s))
    if clip_metadata and clip_metadata.best_segments:
        best = clip_metadata.best_segments[0]
        seg_len = best.end_s - best.start_s
        if seg_len >= target * 0.5:
            start = best.start_s
            end = min(best.end_s, best.start_s + target, source_duration_s)
            if end - start >= 0.5:
                return TrimSelection(
                    start_s=start,
                    end_s=end,
                    reason=best.reason or "best_segment from clip analysis",
                )

    if visual_type == "establishing_shot":
        start = 0.0
        end = min(target, source_duration_s)
        return TrimSelection(start, end, "establishing_shot — début du clip")

    if source_duration_s <= target + 0.01:
        return TrimSelection(0.0, source_duration_s, "clip entier plus court que le beat")

    # Centre du clip
    start = max(0.0, (source_duration_s - target) / 2.0)
    end = min(source_duration_s, start + target)
    return TrimSelection(start, end, f"fenêtre centrée pour « {phrase_anchor[:40]} »")
