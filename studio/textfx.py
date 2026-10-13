"""Texte incrusté ffmpeg : une ligne par `drawtext` (évite le glyphe « \\n »),
taille de police ajustée à la largeur et retour à la ligne automatique."""

from __future__ import annotations

import textwrap
from pathlib import Path

# Police de la charte (Poppins Black, OFL) ; repli DejaVu si le fichier manque.
_POPPINS = Path(__file__).resolve().parent / "workspace" / "anim" / "lib" / "fonts" / "Poppins-Black.ttf"
FONT_FILE = str(_POPPINS) if _POPPINS.exists() else "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
# Largeur moyenne d'un glyphe DejaVu Sans Bold en majuscules, en fraction de la taille.
_GLYPH_WIDTH_EM = 0.72


def wrap_lines(text: str, max_chars: int) -> list[str]:
    """`|` force un retour à la ligne ; les segments trop longs sont replié."""
    lines: list[str] = []
    for part in text.split("|"):
        part = " ".join(part.split())
        if part:
            lines.extend(textwrap.wrap(part, max_chars) or [part])
    return lines


def fit_fontsize(lines: list[str], width: int, base: int, *, margin: float = 0.88) -> int:
    longest = max((len(line) for line in lines), default=1)
    return max(24, min(base, int(width * margin / (_GLYPH_WIDTH_EM * longest))))


def drawtext_chain(
    lines: list[str],
    work_dir: Path,
    prefix: str,
    *,
    fontsize: int,
    y_top: str,
    color: str = "white",
    box: bool = False,
) -> str:
    """Filtres drawtext empilés, à partir de l'expression `y_top` (pixels)."""
    font = f":fontfile={FONT_FILE}" if Path(FONT_FILE).exists() else ""
    border = max(fontsize // 12, 4)
    line_h = int(fontsize * 1.18)
    style = (
        f"fontsize={fontsize}:fontcolor={color}:borderw={border}:bordercolor=black:"
        "shadowcolor=black@0.6:shadowx=4:shadowy=4"
    )
    if box:
        style += ":box=1:boxcolor=black@0.35:boxborderw=14"
    filters: list[str] = []
    for i, line in enumerate(lines):
        text_file = work_dir / f"{prefix}_{i:02d}.txt"
        text_file.write_text(line, encoding="utf-8")
        filters.append(
            f"drawtext=textfile='{text_file}'{font}:{style}:"
            f"x=(w-text_w)/2:y=({y_top})+{i * line_h}"
        )
    return ",".join(filters)


def block_height(n_lines: int, fontsize: int) -> int:
    return int(fontsize * 1.18) * max(n_lines, 1)
