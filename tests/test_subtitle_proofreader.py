from __future__ import annotations

import pytest

from agent.skills.audio.whisper_utils import WordSegment
from agent.skills.subtitle.subtitle_proofreader import proofread_subtitle_segments
from agent.skills.video.viral_subtitles import SubtitleLine, group_words_into_lines


@pytest.mark.asyncio
async def test_proofread_preserves_timestamps() -> None:
    segments = [
        {"start": 0.0, "end": 2.0, "text": "mesaventure historique"},
        {"start": 2.0, "end": 4.0, "text": "la tour de bies"},
    ]

    async def fake_llm(_prompt: str, **_: object) -> str:
        return """[
  {"start": 0.0, "end": 2.0, "text": " mésaventure historique"},
  {"start": 2.0, "end": 4.0, "text": "la tour de Pise"}
]"""

    corrected = await proofread_subtitle_segments(segments, call_llm=fake_llm)
    assert corrected[0]["start"] == 0.0
    assert corrected[0]["end"] == 2.0
    assert "mésaventure" in corrected[0]["text"]
    assert corrected[1]["text"] == "la tour de Pise"


def test_group_words_then_proofread_word_count() -> None:
    words = [
        WordSegment(word="mesaventure", start=0.0, end=0.5),
        WordSegment(word="historique", start=0.5, end=1.0),
    ]
    lines = group_words_into_lines(words, max_words=5, pause_threshold_s=0.4)
    assert len(lines) == 1
    assert isinstance(lines[0], SubtitleLine)
