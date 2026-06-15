from __future__ import annotations

from dataclasses import dataclass
from typing import Any

DERIVATION_ITERATION_BASE = 10_000


def derivation_iteration(short_index: int) -> int:
    return DERIVATION_ITERATION_BASE + short_index


def native_video_type(short_index: int) -> str:
    return f"short_native_{short_index:02d}"


def is_derivation_iteration(iteration: int) -> bool:
    return iteration >= DERIVATION_ITERATION_BASE


@dataclass
class DerivedShortPlan:
    """Mini-scénario pour un short natif dérivé d'une vidéo longue."""

    index: int
    title: str
    hook: str
    cta: str
    segments: list[dict[str, Any]]
    total_duration_s: int
    planned_short: dict[str, Any] | None = None

    def to_scenario_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "segments": self.segments,
            "total_duration_s": self.total_duration_s,
        }
