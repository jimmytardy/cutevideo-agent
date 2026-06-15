from __future__ import annotations

import logging
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from agent.core.visual_beats import TextOverlayPlacement

logger = logging.getLogger(__name__)

_FONT_CANDIDATES = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
)


def _load_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for path in _FONT_CANDIDATES:
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def render_diagram_overlay_png(
    width: int,
    height: int,
    placements: list[TextOverlayPlacement],
    output_path: Path,
) -> Path:
    """Génère un PNG transparent avec labels positionnés (remplace drawtext FFmpeg)."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    canvas = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)

    for placement in placements:
        text = str(placement.text)[:80]
        if not text:
            continue
        fontsize = int(getattr(placement, "fontsize", 36))
        font = _load_font(fontsize)
        x_norm = float(placement.x_norm)
        y_norm = float(placement.y_norm)
        bbox = draw.textbbox((0, 0), text, font=font)
        text_w = bbox[2] - bbox[0]
        text_h = bbox[3] - bbox[1]
        x = int(width * x_norm - text_w / 2)
        y = int(height * y_norm - text_h / 2)

        if getattr(placement, "box", True):
            pad = 6
            draw.rectangle(
                [x - pad, y - pad, x + text_w + pad, y + text_h + pad],
                fill=(0, 0, 0, 153),
            )
        draw.text((x, y), text, font=font, fill=(255, 255, 255, 255))

    canvas.save(output_path, "PNG")
    return output_path


def render_single_text_overlay_png(
    width: int,
    height: int,
    text: str,
    output_path: Path,
    *,
    vertical: bool = False,
    visual_type: str = "",
) -> Path:
    if not text:
        raise ValueError("Texte overlay vide")
    if visual_type in ("quote_card", "statistic_highlight"):
        y_norm = 0.5
        fontsize = 42 if vertical else 48
    else:
        y_norm = 0.75 if vertical else 0.82
        fontsize = 38 if vertical else 44
    placement = TextOverlayPlacement(
        text=text[:80],
        x_norm=0.5,
        y_norm=y_norm,
        fontsize=fontsize,
        box=True,
    )
    return render_diagram_overlay_png(width, height, [placement], output_path)
