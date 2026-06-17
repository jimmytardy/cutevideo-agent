"""Tests découpage beat_planner phase 1 (split_narration_into_beats)."""

from __future__ import annotations

from agent.skills.audio.whisper_utils import WordSegment
from agent.skills.scenario.beat_timeline_split import (
    compute_target_beat_count,
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
