from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from agent.skills.video.montage_decisions import resolve_motion_style
from agent.skills.video.montage_profile import is_short_montage

if TYPE_CHECKING:
    from agent.core.database import Scenario
    from agent.core.orchestrator import PipelineContext

_MOTION_CYCLE = ("zoom_in", "zoom_out", "pan_left", "pan_right")
_ENERGIC_TRANSITIONS = ("pixelize", "wipeleft", "wiperight")


@dataclass(frozen=True)
class BeatPacingHint:
    segment_order: int
    beat_order: int
    motion_hint: str = ""
    transition_hint: str = ""


def apply_pacing_director(
    ctx: "PipelineContext",
    scenario: "Scenario",
) -> dict[tuple[int, int], BeatPacingHint]:
    """Règles de pacing codées pour shorts — hints consommés par MontagePlanner."""
    if not is_short_montage(ctx):
        return {}

    hints: dict[tuple[int, int], BeatPacingHint] = {}
    last_motion = ""

    for seg in scenario.segments or []:
        order = int(seg.get("order", 0))
        beats = seg.get("visual_beats") or []
        if not isinstance(beats, list):
            continue

        delivery = seg.get("delivery_style") or {}
        emphasis = {
            str(w).lower().strip()
            for w in (delivery.get("emphasis_words") or [])
            if str(w).strip()
        }

        for idx, beat in enumerate(beats):
            if not isinstance(beat, dict):
                continue
            beat_order = int(beat.get("order", idx + 1))
            visual_type = str(beat.get("visual_type") or "documentary_photo")
            duration_hint = float(beat.get("duration_hint_s") or 0)

            motion_hint = ""
            transition_hint = ""
            anchor = str(beat.get("phrase_anchor") or "").lower()
            if idx == 0 and order == 1:
                motion_hint = "punch_zoom"
                transition_hint = "pixelize"
            elif emphasis and any(word in anchor for word in emphasis):
                motion_hint = "punch_zoom"
            elif duration_hint > 4.0:
                transition_hint = "wipeleft"

            if not motion_hint:
                candidate = resolve_motion_style(
                    visual_type,
                    "image",
                    index=idx,
                    is_short=True,
                )
                if candidate == last_motion:
                    candidate = _MOTION_CYCLE[(idx + 1) % len(_MOTION_CYCLE)]
                motion_hint = candidate
                last_motion = motion_hint

            hints[(order, beat_order)] = BeatPacingHint(
                segment_order=order,
                beat_order=beat_order,
                motion_hint=motion_hint,
                transition_hint=transition_hint,
            )

    return hints


def pacing_hints_to_dict(
    hints: dict[tuple[int, int], BeatPacingHint],
) -> dict[str, dict[str, str]]:
    return {
        f"{seg}:{beat}": {
            "motion_hint": h.motion_hint,
            "transition_hint": h.transition_hint,
        }
        for (seg, beat), h in hints.items()
    }


def pacing_hints_from_dict(raw: dict[str, Any] | None) -> dict[tuple[int, int], BeatPacingHint]:
    if not raw:
        return {}
    out: dict[tuple[int, int], BeatPacingHint] = {}
    for key, value in raw.items():
        if not isinstance(value, dict):
            continue
        try:
            seg_s, beat_s = str(key).split(":", 1)
            seg, beat = int(seg_s), int(beat_s)
        except ValueError:
            continue
        out[(seg, beat)] = BeatPacingHint(
            segment_order=seg,
            beat_order=beat,
            motion_hint=str(value.get("motion_hint") or ""),
            transition_hint=str(value.get("transition_hint") or ""),
        )
    return out
