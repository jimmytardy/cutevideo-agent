from __future__ import annotations



from dataclasses import dataclass

from typing import TYPE_CHECKING, Any



from agent.skills.video.montage_decisions import resolve_motion_style

from agent.skills.video.montage_profile import is_short_montage, long_pacing_config



if TYPE_CHECKING:

    from agent.core.database import Scenario

    from agent.core.orchestrator import PipelineContext



_MOTION_CYCLE = ("zoom_in", "zoom_out", "pan_left", "pan_right")





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

    """Règles de pacing codées — hints consommés par MontagePlanner."""

    from agent.skills.video.video_style_config import resolve_max_visual_hold_s



    hints: dict[tuple[int, int], BeatPacingHint] = {}

    last_motion = ""

    is_short = is_short_montage(ctx)

    max_hold = resolve_max_visual_hold_s(is_short=is_short)

    long_pacing = (
        long_pacing_config(channel_raw_config=dict(ctx.channel.config or {}))
        if not is_short
        else {}
    )

    mood_transitions = {

        str(k).lower(): str(v)

        for k, v in (long_pacing.get("mood_transitions") or {}).items()

    }

    hook_transition = str(long_pacing.get("hook_transition") or "fadewhite")



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

        seg_mood = str(seg.get("mood") or "calme").lower()



        for idx, beat in enumerate(beats):

            if not isinstance(beat, dict):

                continue

            beat_order = int(beat.get("order", idx + 1))

            visual_type = str(beat.get("visual_type") or "documentary_photo")

            duration_hint = float(beat.get("duration_hint_s") or 0)

            on_screen_text = str(beat.get("on_screen_text") or "").strip()



            motion_hint = ""

            transition_hint = ""

            anchor = str(beat.get("phrase_anchor") or "").lower()

            if visual_type == "statistic_highlight":

                motion_hint = "punch_zoom"

            elif idx == 0 and order == 1 and is_short:

                motion_hint = "punch_zoom"

                transition_hint = "pixelize"

            elif idx == 0 and order == 1 and not is_short:

                motion_hint = "punch_zoom"

                transition_hint = hook_transition

            elif emphasis and any(word in anchor for word in emphasis):

                motion_hint = "punch_zoom"

            elif duration_hint > max_hold:

                transition_hint = "glitch" if not is_short else "wipeleft"

            elif duration_hint > 4.0 and is_short:

                transition_hint = "wipeleft"



            if not is_short:

                if on_screen_text and not transition_hint:

                    transition_hint = "circleopen"

                if not transition_hint and seg_mood in mood_transitions:

                    transition_hint = mood_transitions[seg_mood]

                if idx > 0:

                    prev = beats[idx - 1]

                    if isinstance(prev, dict):

                        prev_duration = float(prev.get("duration_hint_s") or 0)

                        if prev_duration > max_hold and duration_hint > max_hold:

                            transition_hint = transition_hint or "wipeleft"



            if not motion_hint:

                candidate = resolve_motion_style(

                    visual_type,

                    "image",

                    index=idx,

                    is_short=is_short,

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

