from __future__ import annotations

from agent.core.channel_config import VisualBeatsConfig
from agent.core.visual_beats import (
    DiagramLabel,
    VisualBeat,
    effective_min_duration,
    validate_beats_against_narration,
)
from agent.skills.video.diagram_text_layout import (
    fallback_text_layout,
    _resolve_overlaps,
)
from agent.skills.video.ffmpeg_utils import build_multi_drawtext_filter


def test_build_visual_prompt_diagram_forbids_text() -> None:
    from agent.skills.media_sources.ai.prompt_builder import build_visual_prompt

    prompt = build_visual_prompt(
        "scientific_diagram",
        "feather microstructure light trapping",
    )
    lower = prompt.lower()
    assert "no text" in lower
    assert "no labels" in lower


def test_resolved_diagram_labels_from_on_screen_text() -> None:
    beat = VisualBeat(
        order=1,
        phrase_anchor="phrase anchor longue",
        visual_type="scientific_diagram",
        prompt="diagram",
        on_screen_text="Chloroplaste",
    )
    labels = beat.resolved_diagram_labels()
    assert len(labels) == 1
    assert labels[0].text == "Chloroplaste"


def test_effective_min_duration_diagram_longer() -> None:
    cfg = VisualBeatsConfig(min_diagram_duration_s=6.0, min_diagram_duration_short_s=4.0)
    beat = VisualBeat(
        order=1,
        phrase_anchor="phrase anchor longue",
        visual_type="infographic",
        prompt="chart",
        duration_hint_s=8.0,
        diagram_labels=[DiagramLabel(text="Test", role="element")],
    )
    assert effective_min_duration(beat, is_short=False, config=cfg) == 8.0
    photo = VisualBeat(
        order=2,
        phrase_anchor="autre phrase anchor",
        visual_type="documentary_photo",
        prompt="photo",
    )
    assert effective_min_duration(photo, is_short=False, config=cfg) == 4.0


def test_validate_diagram_requires_labels_and_duration() -> None:
    segment = {
        "narration_text": "Le chloroplaste absorbe la lumière du soleil.",
        "visual_beats": [
            {
                "order": 1,
                "phrase_anchor": "chloroplaste absorbe",
                "visual_type": "scientific_diagram",
                "prompt": "cell diagram",
            }
        ],
    }
    errors = validate_beats_against_narration(
        segment,
        vb_config=VisualBeatsConfig(),
        is_short=False,
    )
    assert any("diagram_labels" in e for e in errors)
    assert any("duration_hint_s" in e for e in errors)


def test_fallback_text_layout_stacks_labels() -> None:
    labels = [
        DiagramLabel(text="A", role="a"),
        DiagramLabel(text="B", role="b"),
    ]
    placements = fallback_text_layout(labels, vertical=False)
    assert len(placements) == 2
    assert placements[0].y_norm > placements[1].y_norm


def test_build_multi_drawtext_filter() -> None:
    placements = fallback_text_layout(
        [DiagramLabel(text="Mitochondrie", role="organe")],
        vertical=False,
    )
    vf = build_multi_drawtext_filter(placements)
    assert vf is not None
    assert "drawtext" in vf
    assert "Mitochondrie" in vf


def test_resolve_overlaps_separates_close_labels() -> None:
    from agent.core.visual_beats import TextOverlayPlacement

    placements = [
        TextOverlayPlacement(text="A", x_norm=0.5, y_norm=0.5),
        TextOverlayPlacement(text="B", x_norm=0.51, y_norm=0.5),
    ]
    adjusted = _resolve_overlaps(placements, min_dist=0.08)
    assert adjusted[1].x_norm != placements[1].x_norm
