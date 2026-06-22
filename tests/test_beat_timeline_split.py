"""Tests découpage beat_planner phase 1 (split_narration_into_beats)."""

from __future__ import annotations

from agent.skills.audio.whisper_utils import WordSegment
from agent.skills.scenario.beat_timeline_split import (
    compute_target_beat_count,
    dynamic_max_beats,
    split_narration_into_beats,
)


def _synthetic_words(narration: str, duration_s: float) -> list[WordSegment]:
    tokens = narration.split()
    if not tokens:
        return []
    step = duration_s / len(tokens)
    words: list[WordSegment] = []
    for i, token in enumerate(tokens):
        start = i * step
        end = (i + 1) * step if i < len(tokens) - 1 else duration_s
        words.append(WordSegment(word=token, start=start, end=end))
    return words


def test_split_28s_segment_whisper_anchors() -> None:
    narration = (
        "Les monarques traversent l'Amérique du Nord chaque automne "
        "pour rejoindre leurs sites d'hivernage au Mexique."
    )
    duration_s = 28.0
    words = _synthetic_words(narration, duration_s)
    target = compute_target_beat_count(
        duration_s,
        beat_slot_s=5.0,
        min_beats=3,
        max_beats=8,
    )
    splits = split_narration_into_beats(
        narration,
        words,
        duration_s,
        target_beats=target,
        min_beats=3,
        max_beats=8,
    )
    assert 3 <= len(splits) <= 8
    for split in splits:
        assert split.spoken_text.strip()
        assert split.phrase_anchor.strip()
        assert split.duration_hint_s > 0
    total_hint = sum(s.duration_hint_s for s in splits)
    assert 24.0 <= total_hint <= 30.0


def test_dynamic_max_beats_keeps_base_for_short_segment() -> None:
    # Segment court : le plafond reste à base_max (8), jamais en dessous.
    assert dynamic_max_beats(22.0, min_image_duration_s=4.0, base_max=8) == 8


def test_dynamic_max_beats_scales_up_for_long_segment() -> None:
    # 68 s : un cap fixe à 8 forcerait des plans de 8,5 s+ ; on doit pouvoir
    # découper plus finement (floor(68/4) = 17), borné par hard_ceiling.
    assert dynamic_max_beats(68.0, min_image_duration_s=4.0, base_max=8) == 17
    assert dynamic_max_beats(68.0, min_image_duration_s=4.0, base_max=8) <= 20


def test_dynamic_max_beats_respects_hard_ceiling() -> None:
    assert dynamic_max_beats(300.0, min_image_duration_s=4.0, base_max=8) == 20


def test_long_segment_no_longer_truncated_below_max_static_shot() -> None:
    # Régression : un segment de 68 s ne doit plus produire de plans > max_static_shot_s
    # (8 s). Avec le cap dynamique, le slot pilote vers ~6 s/plan.
    narration = " ".join(f"mot{i}" for i in range(140))
    duration_s = 68.0
    words = _synthetic_words(narration, duration_s)
    seg_max = dynamic_max_beats(duration_s, min_image_duration_s=4.0, base_max=8)
    target = compute_target_beat_count(
        duration_s, beat_slot_s=6.0, min_beats=3, max_beats=seg_max
    )
    splits = split_narration_into_beats(
        narration, words, duration_s, target_beats=target, min_beats=3, max_beats=seg_max
    )
    assert len(splits) > 8
    assert max(s.duration_hint_s for s in splits) <= 8.5
