from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from agent.core.visual_beats import VisualBeat
from agent.skills.audio.whisper_utils import WordSegment


@dataclass(frozen=True)
class BeatSplit:
    order: int
    phrase_anchor: str
    spoken_text: str
    start_s: float
    end_s: float
    duration_hint_s: float


def _normalize(text: str) -> str:
    text = unicodedata.normalize("NFKD", text.lower())
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = re.sub(r"[^\w\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _words_to_text(words: list[WordSegment], start_idx: int, end_idx: int) -> str:
    chunk = words[start_idx:end_idx]
    return " ".join(w.word.strip() for w in chunk if w.word.strip())


def _anchor_from_words(words: list[WordSegment], start_idx: int, window: int = 5) -> str:
    end_idx = min(len(words), start_idx + window)
    anchor = _words_to_text(words, start_idx, end_idx)
    if len(anchor) >= 4:
        return anchor
    return _words_to_text(words, start_idx, min(len(words), start_idx + 8))


def split_narration_into_beats(
    narration_text: str,
    words: list[WordSegment],
    audio_duration_s: float,
    *,
    target_beats: int,
    min_beats: int = 1,
    max_beats: int = 8,
) -> list[BeatSplit]:
    """Découpe une narration en N portions alignées sur Whisper."""
    n = max(min_beats, min(max_beats, target_beats))
    narration = (narration_text or "").strip()
    if not narration:
        return []

    if not words:
        return _proportional_splits(narration, audio_duration_s, n)

    total_words = len(words)
    if total_words < n:
        n = max(1, total_words)

    boundaries: list[int] = [0]
    for i in range(1, n):
        idx = round(i * total_words / n)
        idx = max(boundaries[-1] + 1, min(idx, total_words - (n - i)))
        boundaries.append(idx)
    boundaries.append(total_words)

    splits: list[BeatSplit] = []
    for order, (start_idx, end_idx) in enumerate(
        zip(boundaries[:-1], boundaries[1:], strict=False), start=1
    ):
        if end_idx <= start_idx:
            continue
        start_s = words[start_idx].start
        end_s = words[min(end_idx - 1, len(words) - 1)].end
        if order == n:
            end_s = max(end_s, audio_duration_s)
        spoken = _words_to_text(words, start_idx, end_idx)
        if not spoken.strip():
            spoken = narration
        anchor = _anchor_from_words(words, start_idx)
        splits.append(
            BeatSplit(
                order=order,
                phrase_anchor=anchor[:120],
                spoken_text=spoken,
                start_s=start_s,
                end_s=end_s,
                duration_hint_s=max(end_s - start_s, 0.5),
            )
        )
    return splits


def _proportional_splits(
    narration: str,
    audio_duration_s: float,
    n: int,
) -> list[BeatSplit]:
    tokens = narration.split()
    if not tokens:
        return []
    boundaries = [0]
    for i in range(1, n):
        boundaries.append(round(i * len(tokens) / n))
    boundaries.append(len(tokens))
    splits: list[BeatSplit] = []
    for order, (start_t, end_t) in enumerate(
        zip(boundaries[:-1], boundaries[1:], strict=False), start=1
    ):
        spoken = " ".join(tokens[start_t:end_t])
        start_s = (order - 1) / n * audio_duration_s
        end_s = order / n * audio_duration_s if order < n else audio_duration_s
        splits.append(
            BeatSplit(
                order=order,
                phrase_anchor=spoken[:80] or narration[:80],
                spoken_text=spoken,
                start_s=start_s,
                end_s=end_s,
                duration_hint_s=max(end_s - start_s, 0.5),
            )
        )
    return splits


def compute_target_beat_count(
    audio_duration_s: float,
    *,
    beat_slot_s: float,
    min_beats: int,
    max_beats: int,
) -> int:
    slot = max(beat_slot_s, 1.0)
    raw = max(1, round(audio_duration_s / slot))
    return max(min_beats, min(max_beats, raw))


def beat_slot_seconds(
    *,
    min_image_duration_s: float,
    max_static_shot_s: float,
) -> float:
    return max(2.0, (min_image_duration_s + max_static_shot_s) / 2.0)


def splits_to_visual_beats(
    splits: list[BeatSplit],
    enriched: list[dict],
) -> list[dict]:
    """Fusionne splits temporels + enrichissement LLM."""
    out: list[dict] = []
    for split in splits:
        match = next((e for e in enriched if int(e.get("order", 0)) == split.order), {})
        out.append({
            "order": split.order,
            "phrase_anchor": split.phrase_anchor,
            "spoken_text": split.spoken_text,
            "duration_hint_s": round(split.duration_hint_s, 2),
            "visual_type": match.get("visual_type", "documentary_photo"),
            "prompt": match.get("prompt", split.spoken_text[:200]),
            "style_hint": match.get("style_hint", ""),
            "on_screen_text": match.get("on_screen_text", ""),
            "diagram_labels": match.get("diagram_labels", []),
        })
    return out
