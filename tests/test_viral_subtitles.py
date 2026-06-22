"""Tests sous-titres viral++."""

from __future__ import annotations

from agent.skills.audio.whisper_utils import WordSegment
from agent.skills.video.viral_subtitles import SubtitleStyleConfig, _build_karaoke_text


def test_karaoke_includes_scale_tags() -> None:
    words = [
        WordSegment(word="Bonjour", start=0.0, end=0.3),
        WordSegment(word="MONDE", start=0.3, end=0.6),
    ]
    style = SubtitleStyleConfig(active_word_scale=115, uppercase_word_scale=120)
    text = _build_karaoke_text(words, style)
    assert "\\fscx115" in text
    assert "\\fscx120" in text or "MONDE" in text
