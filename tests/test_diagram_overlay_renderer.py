from __future__ import annotations

from pathlib import Path

from agent.core.visual_beats import TextOverlayPlacement
from agent.skills.video.diagram_overlay_renderer import render_diagram_overlay_png


def test_render_diagram_overlay_png_creates_file(tmp_path: Path) -> None:
    placements = [
        TextOverlayPlacement(text="Chloroplaste", x_norm=0.3, y_norm=0.4, fontsize=32),
    ]
    out = tmp_path / "overlay.png"
    result = render_diagram_overlay_png(1920, 1080, placements, out)
    assert result.exists()
    assert result.stat().st_size > 0
