"""Sous-titres « viraux » des Shorts Claude Studio (ASS rendu par libass).

- 1 à 3 mots par ligne, coupés aux pauses et à la ponctuation ;
- le **mot prononcé** est surligné (couleur + léger grossissement), les autres restent blancs ;
- les **mots-clés** (`timeline.subtitle_keywords`, et tous les nombres) sont en couleur d'accent ;
- chaque ligne apparaît avec un petit « pop » ;
- position haute par défaut (centre du texte à y = 1290 px) : hors de la légende, des boutons et de la
  barre de progression de TikTok / YouTube Shorts (bas ~25 % et colonne droite réservés).
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

from agent.skills.audio.whisper_utils import WordSegment

FONTS_DIR = Path(__file__).resolve().parent / "workspace" / "anim" / "lib" / "fonts"
FONT_NAME = "Poppins ExtraBold"

# Centre vertical du texte selon la position demandée (1920 px de haut).
POSITIONS_Y = {"high": 1290, "center": 960, "low": 1420}
MAX_WORDS = 3
MAX_CHARS = 16
PAUSE_BREAK_S = 0.3
# Une ligne reste affichée jusqu'à la suivante si le trou est court (évite le clignotement).
HOLD_GAP_S = 0.35


@dataclass
class SubtitleStyle:
    font_size: int = 128
    color: str = "#FFFFFF"
    active_color: str = "#FFD60A"
    keyword_color: str = "#4ADE80"
    outline_color: str = "#000000"
    outline: int = 7
    shadow: int = 3
    active_scale: int = 112
    position: str = "high"
    keywords: list[str] = field(default_factory=list)


def _ass_color(hex_color: str, alpha: str = "00") -> str:
    h = hex_color.lstrip("#")
    if len(h) != 6:
        h = "FFFFFF"
    return f"&H{alpha}{h[4:6]}{h[2:4]}{h[0:2]}".upper()


def _ass_time(t: float) -> str:
    t = max(0.0, t)
    cs = int(round(t * 100))
    h, cs = divmod(cs, 360000)
    m, cs = divmod(cs, 6000)
    s, cs = divmod(cs, 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def _norm(word: str) -> str:
    w = unicodedata.normalize("NFKD", word.lower())
    w = "".join(c for c in w if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9%]", "", w)


def _merge_punctuation(words: list[WordSegment]) -> list[WordSegment]:
    """Rattache au mot précédent les « mots » sans lettre ni chiffre (« : », « … ») que Whisper isole."""
    merged: list[WordSegment] = []
    for w in words:
        if merged and not any(c.isalnum() for c in w.word):
            prev = merged[-1]
            merged[-1] = WordSegment(word=prev.word + w.word.strip(), start=prev.start, end=max(prev.end, w.end))
        else:
            merged.append(w)
    return merged


def group_lines(words: list[WordSegment]) -> list[list[WordSegment]]:
    words = _merge_punctuation(words)
    lines: list[list[WordSegment]] = []
    cur: list[WordSegment] = []
    for w in words:
        if cur:
            gap = w.start - cur[-1].end
            chars = sum(len(x.word) + 1 for x in cur) + len(w.word)
            ends_phrase = cur[-1].word.rstrip()[-1:] in ".!?:;,…"
            if gap > PAUSE_BREAK_S or len(cur) >= MAX_WORDS or chars > MAX_CHARS or ends_phrase:
                lines.append(cur)
                cur = []
        cur.append(w)
    if cur:
        lines.append(cur)
    return lines


def _is_keyword(word: str, keywords: set[str]) -> bool:
    n = _norm(word)
    return bool(n) and (n in keywords or any(c.isdigit() for c in n))


def build_ass(words: list[WordSegment], style: SubtitleStyle) -> str:
    y = POSITIONS_Y.get(style.position, POSITIONS_Y["high"])
    keywords = {_norm(k) for kw in style.keywords for k in kw.split() if _norm(k)}
    header = (
        "[Script Info]\nScriptType: v4.00+\nPlayResX: 1080\nPlayResY: 1920\nWrapStyle: 2\n"
        "ScaledBorderAndShadow: yes\n\n[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, "
        "Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, "
        "MarginL, MarginR, MarginV, Encoding\n"
        f"Style: Sub,{FONT_NAME},{style.font_size},{_ass_color(style.color)},{_ass_color(style.color)},"
        f"{_ass_color(style.outline_color)},{_ass_color('#000000', '80')},0,0,0,0,100,100,1,0,1,"
        f"{style.outline},{style.shadow},5,60,60,0,1\n\n"
        "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )
    lines = group_lines(words)
    events: list[str] = []
    for li, line in enumerate(lines):
        next_start = lines[li + 1][0].start if li + 1 < len(lines) else None
        line_end = line[-1].end
        if next_start is not None and next_start - line_end <= HOLD_GAP_S:
            line_end = next_start
        else:
            line_end += 0.15
        for wi, active in enumerate(line):
            start = line[0].start if wi == 0 else active.start
            end = line[wi + 1].start if wi + 1 < len(line) else line_end
            parts = []
            for k, w in enumerate(line):
                text = w.word.replace("{", "").replace("}", "").strip()
                if not text:
                    continue
                if k == wi:
                    parts.append(
                        f"{{\\c{_ass_color(style.active_color)}\\fscx{style.active_scale}\\fscy{style.active_scale}}}"
                        f"{text}{{\\c{_ass_color(style.color)}\\fscx100\\fscy100}}"
                    )
                elif _is_keyword(text, keywords):
                    parts.append(f"{{\\c{_ass_color(style.keyword_color)}}}{text}{{\\c{_ass_color(style.color)}}}")
                else:
                    parts.append(text)
            # Apparition en fondu court de chaque nouvelle ligne.
            pop = "\\fad(70,0)" if wi == 0 else ""
            events.append(
                f"Dialogue: 0,{_ass_time(start)},{_ass_time(end)},Sub,,0,0,0,,"
                f"{{\\an5\\pos(540,{y}){pop}}}{' '.join(parts)}"
            )
    return header + "\n".join(events) + "\n"


def write_ass(words: list[WordSegment], style: SubtitleStyle, out: Path) -> Path:
    out.write_text(build_ass(words, style), encoding="utf-8")
    return out


def ass_filter(ass: Path) -> str:
    """Filtre ffmpeg `ass=` avec les polices embarquées du studio."""

    def esc(p: Path) -> str:
        return str(p).replace("\\", "/").replace(":", "\\:").replace("'", "\\'")

    return f"ass={esc(ass)}:fontsdir={esc(FONTS_DIR)}"
