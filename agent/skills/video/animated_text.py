from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from agent.skills.video.viral_subtitles import _hex_to_ass_color, _seconds_to_ass_time
from agent.skills.video.video_style_config import TextOverlayAnimationConfig

_REVEAL_HOOKS = frozenset({"fait_surprenant", "revelateur", "révélateur", "chiffre"})
_NUMBER_RE = re.compile(r"\d[\d\s.,%]*")


@dataclass(frozen=True)
class TextOverlayEvent:
    start_s: float
    end_s: float
    text: str
    animation: str
    visual_type: str = ""
    vertical: bool = False


def parse_animation_styles(raw: str) -> list[str]:
    return [part.strip() for part in (raw or "").split("+") if part.strip()]


def build_animated_overlay_ass(
    events: list[TextOverlayEvent],
    style_cfg: TextOverlayAnimationConfig,
    *,
    play_res_x: int = 1920,
    play_res_y: int = 1080,
) -> str:
    """Génère un fichier ASS d'overlays on-screen animés."""
    highlight = _hex_to_ass_color(style_cfg.highlight_color)
    glow_blur = max(1, int(style_cfg.glow_intensity * 6))
    margin_v = int(play_res_y * (0.18 if play_res_x < play_res_y else 0.12))
    font_size = 68 if play_res_x < play_res_y else 52

    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {play_res_x}
PlayResY: {play_res_y}
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Overlay,DejaVu Sans,{font_size},&H00FFFFFF,&H00FFFFFF,&H00000000,&H80000000,1,0,0,0,100,100,0,0,1,3,0,2,40,40,{margin_v},1
Style: Neon,DejaVu Sans,{font_size + 4},&H00FFFFFF,&H00FFFFFF,{highlight},&H40000000,1,0,0,0,100,100,0,0,1,5,0,2,40,40,{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    lines: list[str] = []
    for event in events:
        styles = parse_animation_styles(event.animation)
        primary_style = "Neon" if "neon_glow" in styles else "Overlay"
        for dialogue in _events_for_animation(event, styles, highlight, glow_blur):
            start = _seconds_to_ass_time(dialogue["start"])
            end = _seconds_to_ass_time(dialogue["end"])
            lines.append(
                f"Dialogue: 0,{start},{end},{primary_style},,0,0,0,,{dialogue['text']}"
            )

    return header + "\n".join(lines) + "\n"


def write_animated_overlay_ass(
    events: list[TextOverlayEvent],
    style_cfg: TextOverlayAnimationConfig,
    output_path: Path,
    *,
    play_res_x: int = 1920,
    play_res_y: int = 1080,
) -> Path:
    content = build_animated_overlay_ass(
        events,
        style_cfg,
        play_res_x=play_res_x,
        play_res_y=play_res_y,
    )
    output_path.write_text(content, encoding="utf-8")
    return output_path


def collect_overlay_events_from_plan(
    plan_data: object,
    *,
    is_vertical: bool,
) -> list[TextOverlayEvent]:
    """Collecte les overlays ASS depuis un MontagePlanData."""
    from agent.core.montage_plan import MontagePlanData

    if not isinstance(plan_data, MontagePlanData):
        plan_data = MontagePlanData.from_db_dict(plan_data)  # type: ignore[arg-type]

    events: list[TextOverlayEvent] = []
    segment_offset = 0.0
    for seg in sorted(plan_data.segments, key=lambda s: s.segment_order):
        for clip in seg.clips:
            if clip.overlay_mode != "ass_overlay" or not clip.on_screen_text.strip():
                continue
            animation = str(getattr(clip, "text_animation", "") or "")
            if not animation:
                from agent.skills.video.montage_decisions import resolve_text_animation

                animation = resolve_text_animation(clip.visual_type)
            start = segment_offset + clip.timeline_start_s
            end = segment_offset + clip.timeline_end_s
            events.append(
                TextOverlayEvent(
                    start_s=start,
                    end_s=max(end, start + 0.5),
                    text=clip.on_screen_text.strip(),
                    animation=animation,
                    visual_type=clip.visual_type,
                    vertical=is_vertical,
                )
            )
        if seg.clips:
            segment_offset += seg.clips[-1].timeline_end_s
    return events


def _events_for_animation(
    event: TextOverlayEvent,
    styles: list[str],
    highlight: str,
    glow_blur: int,
) -> list[dict[str, float | str]]:
    text = _escape_ass_text(event.text[:120])
    duration = max(event.end_s - event.start_s, 0.4)

    if "typewriter" in styles:
        return _typewriter_dialogues(event.start_s, duration, text)

    tags: list[str] = []
    if "pop_bounce" in styles:
        tags.append(r"\fad(80,120)\t(0,180,\fscx120\fscy120)\t(180,320,\fscx100\fscy100)")
    if "mask_reveal" in styles:
        tags.append(r"\clip(0,0,0,0)\t(0,400,\clip(0,0,1920,1080))")
    if "neon_glow" in styles:
        tags.append(f"\\blur{glow_blur}\\3c{highlight}\\bord4")
    if "highlight" in styles:
        text = _apply_highlight_tags(text, highlight)

    prefix = "{" + "".join(tags) + "}" if tags else ""
    return [{
        "start": event.start_s,
        "end": event.start_s + duration,
        "text": f"{prefix}{text}",
    }]


def _typewriter_dialogues(
    start_s: float,
    duration: float,
    text: str,
) -> list[dict[str, float | str]]:
    chars = list(text.replace(" ", "\u00a0"))
    if not chars:
        return [{"start": start_s, "end": start_s + duration, "text": text}]
    step = duration / len(chars)
    dialogues: list[dict[str, float | str]] = []
    for idx in range(1, len(chars) + 1):
        partial = "".join(chars[:idx])
        dialogues.append({
            "start": start_s + step * (idx - 1),
            "end": start_s + step * idx,
            "text": partial,
        })
    return dialogues


def _apply_highlight_tags(text: str, highlight: str) -> str:
    def repl_number(match: re.Match[str]) -> str:
        return f"{{\\c{highlight}\\bord2}}{match.group(0)}{{\\r}}"

    text = _NUMBER_RE.sub(repl_number, text)
    parts: list[str] = []
    for token in text.split(" "):
        if token.isupper() and len(token) > 1:
            parts.append(f"{{\\c{highlight}\\bord2}}{token}{{\\r}}")
        else:
            parts.append(token)
    return " ".join(parts)


def _escape_ass_text(text: str) -> str:
    return text.replace("{", "").replace("}", "").replace("\n", " ")
