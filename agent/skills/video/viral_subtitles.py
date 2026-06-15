from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from agent.skills.audio.whisper_utils import WordSegment

logger = logging.getLogger(__name__)


@dataclass
class SubtitleLine:
    words: list[WordSegment]

    @property
    def start(self) -> float:
        return self.words[0].start

    @property
    def end(self) -> float:
        return self.words[-1].end


@dataclass
class SubtitleStyleConfig:
    font_name: str = "DejaVu Sans"
    font_size: int = 68
    primary_color: str = "#FFFFFF"
    highlight_color: str = "#FFE600"
    outline_color: str = "#000000"
    outline_width: int = 4
    margin_v: int = 120
    play_res_x: int = 1080
    play_res_y: int = 1920


def group_words_into_lines(
    words: list[WordSegment],
    *,
    max_words: int = 3,
    pause_threshold_s: float = 0.4,
) -> list[SubtitleLine]:
    """Regroupe les mots en lignes courtes (style viral)."""
    if not words:
        return []

    lines: list[SubtitleLine] = []
    current: list[WordSegment] = []

    for word in words:
        if current:
            gap = word.start - current[-1].end
            if gap > pause_threshold_s or len(current) >= max_words:
                lines.append(SubtitleLine(words=current))
                current = []

        current.append(word)

    if current:
        lines.append(SubtitleLine(words=current))

    return lines


def build_karaoke_ass(
    lines: list[SubtitleLine],
    style: SubtitleStyleConfig,
) -> str:
    """Génère le contenu d'un fichier ASS avec effet karaoké mot-à-mot."""
    primary = _hex_to_ass_color(style.primary_color)
    highlight = _hex_to_ass_color(style.highlight_color)
    outline = _hex_to_ass_color(style.outline_color)

    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {style.play_res_x}
PlayResY: {style.play_res_y}
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Viral,{style.font_name},{style.font_size},{primary},{highlight},{outline},&H80000000,1,0,0,0,100,100,0,0,1,{style.outline_width},0,2,40,40,{style.margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    events: list[str] = []
    for line in lines:
        start = _seconds_to_ass_time(line.start)
        end = _seconds_to_ass_time(line.end)
        karaoke_text = _build_karaoke_text(line.words)
        if karaoke_text:
            events.append(
                f"Dialogue: 0,{start},{end},Viral,,0,0,0,,{karaoke_text}"
            )

    return header + "\n".join(events) + "\n"


def write_ass_file(lines: list[SubtitleLine], style: SubtitleStyleConfig, output_path: Path) -> Path:
    """Écrit le fichier ASS sur disque."""
    content = build_karaoke_ass(lines, style)
    output_path.write_text(content, encoding="utf-8")
    logger.info("ASS karaoké généré : %d lignes → %s", len(lines), output_path)
    return output_path


def write_srt_from_lines(lines: list[SubtitleLine], output_path: Path) -> None:
    """Génère un fichier SRT à partir des lignes de sous-titres groupées."""
    segments = [
        {
            "start": line.start,
            "end": line.end,
            "text": " ".join(w.word for w in line.words),
        }
        for line in lines
    ]
    from agent.skills.audio.whisper_utils import _build_srt

    output_path.write_text(_build_srt(segments), encoding="utf-8")


async def burn_ass_subtitles(
    video_path: Path,
    ass_path: Path,
    output_path: Path,
) -> None:
    """Incruste les sous-titres ASS dans une vidéo via FFmpeg."""
    from agent.skills.video.ffmpeg_utils import _run_ffmpeg

    ass_escaped = str(ass_path.resolve()).replace("\\", "/").replace(":", "\\:")
    cmd = [
        "ffmpeg", "-y",
        "-i", str(video_path),
        "-vf", f"ass={ass_escaped}",
        "-c:v", "libx264", "-crf", "20", "-preset", "medium",
        "-c:a", "copy",
        "-movflags", "+faststart",
        str(output_path),
    ]
    await _run_ffmpeg(cmd)
    logger.info("Sous-titres incrustés → %s", output_path)


def style_from_config(subtitles_cfg: object) -> SubtitleStyleConfig:
    """Construit SubtitleStyleConfig depuis SubtitleConfig ou dict."""
    if hasattr(subtitles_cfg, "model_dump"):
        data = subtitles_cfg.model_dump()
    elif isinstance(subtitles_cfg, dict):
        data = subtitles_cfg
    else:
        data = {}

    return SubtitleStyleConfig(
        font_name=str(data.get("font_name", "DejaVu Sans")),
        font_size=int(data.get("font_size", 68)),
        primary_color=str(data.get("primary_color", "#FFFFFF")),
        highlight_color=str(data.get("highlight_color", "#FFE600")),
        outline_color=str(data.get("outline_color", "#000000")),
        outline_width=int(data.get("outline_width", 4)),
        margin_v=int(data.get("margin_v", 120)),
        play_res_x=int(data.get("play_res_x", 1080)),
        play_res_y=int(data.get("play_res_y", 1920)),
    )


def _build_karaoke_text(words: list[WordSegment]) -> str:
    parts: list[str] = []
    for w in words:
        duration_cs = max(1, int((w.end - w.start) * 100))
        safe = w.word.replace("{", "").replace("}", "").strip()
        if safe:
            parts.append(f"{{\\k{duration_cs}}}{safe}")
    return " ".join(parts)


def _hex_to_ass_color(hex_color: str) -> str:
    hex_color = hex_color.lstrip("#")
    if len(hex_color) != 6:
        return "&H00FFFFFF"
    r = int(hex_color[0:2], 16)
    g = int(hex_color[2:4], 16)
    b = int(hex_color[4:6], 16)
    return f"&H00{b:02X}{g:02X}{r:02X}"


def _seconds_to_ass_time(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    cs = int(round((s % 1) * 100)) % 100
    sec_int = int(s)
    return f"{h}:{m:02d}:{sec_int:02d}.{cs:02d}"
