"""Tests extraction grammaire de montage et mapping vers montage_profile."""

from __future__ import annotations

from agent.skills.video.style_extractor import (
    BEAT_SLOT_MAX,
    BEAT_SLOT_MIN,
    EditGrammar,
    aggregate_edit_grammars,
    clamp,
    edit_grammar_to_montage_profile,
)


def test_clamp_bounds() -> None:
    assert clamp(0.5, BEAT_SLOT_MIN, BEAT_SLOT_MAX) == BEAT_SLOT_MIN
    assert clamp(10.0, BEAT_SLOT_MIN, BEAT_SLOT_MAX) == BEAT_SLOT_MAX
    assert clamp(2.5, BEAT_SLOT_MIN, BEAT_SLOT_MAX) == 2.5


def test_aggregate_edit_grammars_median() -> None:
    g1 = EditGrammar(avg_shot_duration_s=2.0, is_short_format=True)
    g2 = EditGrammar(avg_shot_duration_s=4.0, is_short_format=True)
    agg = aggregate_edit_grammars([g1, g2])
    assert agg.avg_shot_duration_s == 3.0
    assert agg.is_short_format is True


def test_to_montage_profile_clamps_beat_slot() -> None:
    grammar = EditGrammar(
        avg_shot_duration_s=0.5,
        pattern_interrupts_per_min=50.0,
        dominant_transitions=["invalid_transition_xyz"],
        is_short_format=True,
    )
    profile = edit_grammar_to_montage_profile(grammar, None, reference_count=1)
    short = profile["short_montage_profile"]
    assert short["beat_slot_s"] == BEAT_SLOT_MIN
    assert short["sfx"]["max_cues_per_minute"] == 20
    mood = short["transitions"]["mood_defaults"]
    assert all(v == "fade" for v in mood.values())


def test_to_montage_profile_long_inter_segment_flash() -> None:
    grammar = EditGrammar(
        inter_segment_flash_detected=True,
        avg_transition_duration_s=0.5,
        is_short_format=False,
        hook_transition_style="fadewhite",
    )
    profile = edit_grammar_to_montage_profile(None, grammar, reference_count=2)
    long_prof = profile["long_montage_profile"]
    assert long_prof["inter_segment_flash"] is True
    assert long_prof["pacing"]["hook_transition"] == "fadewhite"
    assert profile["meta"]["reference_count"] == 2


def test_edit_grammar_from_gemini_data_normalizes_caption() -> None:
    g = EditGrammar.from_gemini_data({"caption_style": "unknown", "dominant_transitions": []})
    assert g.caption_style == "karaoke"
    assert g.dominant_transitions == ["fade"]
