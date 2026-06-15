"""Tests dérivation validation média par beat."""

from __future__ import annotations

from agent.core.beat_validation import (
    resolve_beat_validation,
    resolve_beats_for_response,
    resolve_segment_classic_validation,
)
from agent.core.media_validation import MediaValidationBrief, SegmentValidationBrief
from agent.core.visual_beats import VisualBeat


def _wildlife_beat() -> VisualBeat:
    return VisualBeat(
        order=1,
        phrase_anchor="le mâle noir danse",
        visual_type="wildlife_action",
        prompt="Parade nuptiale du paradisier superbe",
    )


def _map_beat() -> VisualBeat:
    return VisualBeat(
        order=2,
        phrase_anchor="traversent le continent",
        visual_type="map",
        prompt="Carte de migration des monarques",
        duration_hint_s=6.0,
    )


def test_resolve_beat_validation_wildlife_includes_species_context() -> None:
    brief = MediaValidationBrief(
        subject_entity="Lophorina superba",
        subject_type="species",
        must_include=["parade nuptiale"],
        must_exclude=["paon"],
        ambiguity_warnings=["confusion avec paon"],
        min_relevance_score=75,
    )
    ctx = resolve_beat_validation(_wildlife_beat(), brief=brief, segment_order=1)

    assert "parade nuptiale" in ctx.must_include
    assert "paon" in ctx.must_exclude
    assert "wildlife_action" in ctx.layers[-1]
    assert ctx.min_relevance_score == 75


def test_resolve_beat_validation_diagram_lowers_threshold() -> None:
    brief = MediaValidationBrief(min_relevance_score=75)
    ctx = resolve_beat_validation(_map_beat(), brief=brief, segment_order=1)

    assert ctx.min_relevance_score == 70
    assert "clarté visuelle" in ctx.must_include
    assert "carte ou schéma générique" in ctx.must_exclude
    assert "visual_type:map" in ctx.layers


def test_resolve_beat_validation_merges_segment_override() -> None:
    brief = MediaValidationBrief(
        subject_entity="Monarque",
        must_include=["global"],
        must_exclude=["paon"],
        segments={
            1: SegmentValidationBrief(
                must_include=["segment_specific"],
                must_exclude=["autre espèce"],
                min_relevance_score=80,
            ),
        },
    )
    ctx = resolve_beat_validation(_wildlife_beat(), brief=brief, segment_order=1)

    assert "segment_specific" in ctx.must_include
    assert "autre espèce" in ctx.must_exclude
    assert "segment" in ctx.layers
    assert ctx.min_relevance_score == 80


def test_min_score_for_beat_on_brief() -> None:
    brief = MediaValidationBrief(min_relevance_score=75)
    score = brief.min_score_for_beat(1, _map_beat())
    assert score == 70


def test_resolve_segment_classic_validation() -> None:
    brief = MediaValidationBrief(
        must_include=["global_item"],
        segments={
            2: SegmentValidationBrief(must_include=["seg2"], must_exclude=["x"]),
        },
    )
    ctx = resolve_segment_classic_validation(brief=brief, segment_order=2)

    assert ctx.must_include == ["seg2"]
    assert ctx.must_exclude == ["x"]
    assert "segment_classic" in ctx.layers


def test_resolve_beats_for_response_with_and_without_beats() -> None:
    brief = MediaValidationBrief(
        subject_entity="Test",
        min_relevance_score=70,
    )
    segments = [
        {
            "order": 1,
            "title": "Intro",
            "visual_beats": [
                {
                    "order": 1,
                    "phrase_anchor": "ancre test",
                    "visual_type": "wildlife_action",
                    "prompt": "Animal en action",
                },
            ],
        },
        {
            "order": 2,
            "title": "Sans beats",
        },
    ]
    resolved = resolve_beats_for_response(brief, segments)

    assert len(resolved) == 2
    assert resolved[0]["beat_order"] == 1
    assert resolved[0]["visual_type"] == "wildlife_action"
    assert resolved[1]["beat_order"] is None
    assert resolved[1]["segment_title"] == "Sans beats"
