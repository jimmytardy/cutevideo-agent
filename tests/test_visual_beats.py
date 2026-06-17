from __future__ import annotations

from agent.core.visual_beats import (
    VisualBeat,
    beat_narration_excerpt,
    parse_visual_beats,
    validate_beats_against_narration,
)
from agent.skills.media.segment_beats_media import ensure_visual_beats_on_segments
from agent.skills.media_sources.ai.prompt_builder import (
    build_visual_prompt,
    is_known_visual_type,
    list_visual_types,
)


def test_beat_narration_excerpt_prefers_spoken_text() -> None:
    beat = VisualBeat(
        order=1,
        phrase_anchor="ancre courte",
        visual_type="documentary_photo",
        prompt="photo",
        spoken_text="Texte complet prononcé pour ce beat.",
    )
    assert beat_narration_excerpt(beat) == "Texte complet prononcé pour ce beat."


def test_visual_beat_custom_requires_style_hint_filled_from_prompt() -> None:
    beat = VisualBeat(
        order=1,
        phrase_anchor="test anchor phrase here",
        visual_type="custom",
        prompt="A surreal political cartoon",
        style_hint="",
    )
    assert beat.style_hint


def test_parse_visual_beats_sorts_by_order() -> None:
    segment = {
        "narration_text": "Première phrase. Deuxième phrase longue.",
        "visual_beats": [
            {"order": 2, "phrase_anchor": "Deuxième", "visual_type": "infographic", "prompt": "chart"},
            {"order": 1, "phrase_anchor": "Première", "visual_type": "documentary_photo", "prompt": "photo"},
        ],
    }
    beats = parse_visual_beats(segment)
    assert [b.order for b in beats] == [1, 2]


def test_validate_beats_against_narration_ok() -> None:
    segment = {
        "narration_text": "Le Paradisier superbe absorbe la lumière.",
        "visual_beats": [
            {
                "order": 1,
                "phrase_anchor": "Paradisier superbe",
                "visual_type": "documentary_photo",
                "prompt": "bird",
            }
        ],
    }
    assert validate_beats_against_narration(segment) == []


def test_ensure_visual_beats_strips_voice_segments() -> None:
    segment = {
        "needs_voice": True,
        "title": "Hook",
        "narration_text": "Phrase un. Phrase deux. Phrase trois.",
        "visual_beats": [{"order": 1, "phrase_anchor": "Phrase un", "visual_type": "documentary_photo", "prompt": "x"}],
    }
    result = ensure_visual_beats_on_segments(
        [segment],
        is_short=True,
        min_beats=3,
        max_beats=8,
        editorial_tone="documentaire",
        theme_category="nature",
    )
    assert "visual_beats" not in result[0]


def test_ensure_visual_beats_fallback_no_voice() -> None:
    segment = {
        "needs_voice": False,
        "title": "Hook",
        "narration_text": "",
        "on_screen_text": "Label",
    }
    result = ensure_visual_beats_on_segments(
        [segment],
        is_short=True,
        min_beats=3,
        max_beats=8,
        editorial_tone="documentaire",
        theme_category="nature",
    )
    beats = result[0]["visual_beats"]
    assert len(beats) >= 1
    assert beats[0]["on_screen_text"] == "Label"


def test_build_visual_prompt_diagram_forbids_text() -> None:
    prompt = build_visual_prompt(
        "scientific_diagram",
        "feather microstructure light trapping",
    )
    lower = prompt.lower()
    assert "no text" in lower
    assert "no labels" in lower


def test_unknown_visual_type_becomes_custom() -> None:
    beat = VisualBeat(
        order=1,
        phrase_anchor="anchor phrase long enough",
        visual_type="unknown_future_type",
        prompt="something visual",
    )
    assert beat.visual_type == "custom"


def test_registry_has_many_types() -> None:
    types = list_visual_types()
    assert len(types) >= 20
    assert is_known_visual_type("news_broll")
    assert is_known_visual_type("meme_template")


class _MsCfg:
    def __init__(self, prefer_video: bool) -> None:
        self.prefer_video = prefer_video


def test_beat_video_target_prefers_stock_video_for_documentary() -> None:
    from agent.skills.media.segment_beats_media import _beat_video_target

    beat = VisualBeat(
        order=1,
        phrase_anchor="oiseau dans la forêt tropicale",
        visual_type="documentary_photo",
        prompt="bird in rainforest",
    )
    assert _beat_video_target(beat, _MsCfg(prefer_video=True)) == 1
    assert _beat_video_target(beat, _MsCfg(prefer_video=False)) == 0


def test_beat_video_target_skips_diagrams() -> None:
    from agent.skills.media.segment_beats_media import _beat_video_target

    beat = VisualBeat(
        order=1,
        phrase_anchor="structure des plumes",
        visual_type="scientific_diagram",
        prompt="feather cross section",
    )
    assert _beat_video_target(beat, _MsCfg(prefer_video=True)) == 0
