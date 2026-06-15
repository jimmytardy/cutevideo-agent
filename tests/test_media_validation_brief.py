"""Tests brief de validation média."""

from __future__ import annotations

from agent.core.media_validation import (
    MediaValidationBrief,
    SegmentValidationBrief,
    attach_brief_to_segments,
    resolve_validation_brief,
)
from agent.skills.media_sources.relevance_scorer import build_relevance_prompt


def test_resolve_validation_brief_ignores_stale_project_override() -> None:
    auto = MediaValidationBrief(
        subject_entity="Lophorina superba",
        subject_type="species",
        must_include=["parade nuptiale"],
        must_exclude=["paon"],
        min_relevance_score=75,
        niche_risk="high",
    )
    brief = resolve_validation_brief(
        channel_config={},
        project_config={
            "media_validation_brief": auto.to_dict(),
            "media_validation_override": {
                "must_exclude": ["perroquet"],
                "validation_prompt": "Exiger mâle noir uniquement",
                "min_relevance_score": 80,
            },
        },
        scenario_segments=[],
        theme_category="nature",
    )
    assert brief.must_exclude == ["paon"]
    assert "perroquet" not in brief.must_exclude
    assert brief.min_relevance_score == 75
    assert "mâle noir" not in brief.validation_prompt


def test_resolve_validation_brief_channel_template() -> None:
    brief = resolve_validation_brief(
        channel_config={
            "media_validation": {
                "media_validation_template": "Rejeter toute image floue",
                "default_min_relevance_score": 70,
            }
        },
        project_config={},
        scenario_segments=[],
        theme_category="science",
    )
    assert brief.min_relevance_score == 70
    assert "floue" in brief.validation_prompt


def test_attach_brief_to_segments() -> None:
    from agent.core.media_validation import SegmentValidationBrief

    brief = MediaValidationBrief(
        subject_entity="Test",
        must_include=["a"],
        segments={
            1: SegmentValidationBrief(must_include=["segment1"], must_exclude=["x"]),
        },
    )
    segments = attach_brief_to_segments(
        [{"order": 1, "title": "Intro", "search_keywords": ["kw"]}],
        brief,
    )
    assert segments[0]["media_validation"]["subject_entity"] == "Test"
    assert "segment1" in segments[0]["media_validation"]["must_include"]


def test_build_relevance_prompt_includes_must_exclude() -> None:
    brief = MediaValidationBrief(
        subject_entity="Lophorina superba",
        subject_type="species",
        must_include=["parade"],
        must_exclude=["paon", "perroquet"],
        ambiguity_warnings=["confusion avec paon"],
        validation_prompt="Espèce exacte obligatoire",
    )
    prompt = build_relevance_prompt(
        video_subject="Paradisier superbe",
        channel_category="nature",
        segment_title="Parade",
        segment_narration="Le mâle noir danse",
        validation_brief=brief,
        segment_order=1,
    )
    assert "Lophorina superba" in prompt
    assert "paon" in prompt
    assert "Score < 30" in prompt


def test_build_relevance_prompt_species_segment_override() -> None:
    from agent.core.media_validation import SegmentValidationBrief

    brief = MediaValidationBrief(
        subject_entity="Lophorina superba",
        subject_type="species",
        must_include=["global"],
        must_exclude=["paon"],
        segments={
            2: SegmentValidationBrief(
                must_include=["segment2_specific"],
                must_exclude=["autre"],
            ),
        },
    )
    prompt = build_relevance_prompt(
        video_subject="Sujet",
        channel_category="nature",
        segment_title="Seg2",
        segment_narration="",
        validation_brief=brief,
        segment_order=2,
    )
    assert "segment2_specific" in prompt


def test_build_relevance_prompt_with_beat_includes_visual_type() -> None:
    from agent.core.visual_beats import VisualBeat

    brief = MediaValidationBrief(
        subject_entity="Monarque",
        subject_type="species",
        must_include=["migration"],
        must_exclude=["papillon générique"],
        min_relevance_score=75,
    )
    beat = VisualBeat(
        order=1,
        phrase_anchor="traversent l'Amérique",
        visual_type="map",
        prompt="Carte des routes de migration",
        duration_hint_s=6.0,
    )
    prompt = build_relevance_prompt(
        video_subject="Migration des monarques",
        channel_category="nature",
        segment_title="Migration",
        segment_narration="Les monarques traversent l'Amérique",
        validation_brief=brief,
        segment_order=1,
        beat=beat,
    )
    assert "INTENTION VISUELLE DU BEAT" in prompt
    assert "map" in prompt
    assert "Carte des routes de migration" in prompt
    assert "clarté visuelle" in prompt
