from __future__ import annotations

from agent.skills.audio.whisper_utils import WordSegment
from agent.skills.video.viral_subtitles import (
    SubtitleLine,
    SubtitleStyleConfig,
    build_karaoke_ass,
    group_words_into_lines,
    style_from_config,
)


def _word(text: str, start: float, end: float) -> WordSegment:
    return WordSegment(word=text, start=start, end=end)


def test_group_words_respects_max_words() -> None:
    words = [
        _word("un", 0.0, 0.2),
        _word("deux", 0.3, 0.5),
        _word("trois", 0.6, 0.8),
        _word("quatre", 0.9, 1.1),
    ]
    lines = group_words_into_lines(words, max_words=3, pause_threshold_s=0.4)
    assert len(lines) == 2
    assert len(lines[0].words) == 3
    assert len(lines[1].words) == 1


def test_group_words_splits_on_pause() -> None:
    words = [
        _word("bonjour", 0.0, 0.3),
        _word("monde", 0.35, 0.6),
        _word("salut", 1.2, 1.5),
    ]
    lines = group_words_into_lines(words, max_words=5, pause_threshold_s=0.4)
    assert len(lines) == 2
    assert [w.word for w in lines[0].words] == ["bonjour", "monde"]
    assert [w.word for w in lines[1].words] == ["salut"]


def test_group_words_empty() -> None:
    assert group_words_into_lines([]) == []


def test_build_karaoke_ass_contains_k_tags() -> None:
    lines = [
        SubtitleLine(words=[_word("Voici", 1.0, 1.4), _word("le", 1.45, 1.6)]),
    ]
    style = SubtitleStyleConfig()
    ass = build_karaoke_ass(lines, style)
    assert "[Script Info]" in ass
    assert "Style: Viral" in ass
    assert "{\\k" in ass
    assert "Voici" in ass
    assert "le" in ass
    assert "Dialogue: 0,0:00:01.00,0:00:01.60,Viral" in ass


def test_hex_to_ass_colors_in_style() -> None:
    lines = [SubtitleLine(words=[_word("test", 0.0, 0.5)])]
    style = SubtitleStyleConfig(
        primary_color="#FFFFFF",
        highlight_color="#FFE600",
        outline_color="#000000",
    )
    ass = build_karaoke_ass(lines, style)
    assert "&H00FFFFFF" in ass
    assert "&H0000E6FF" in ass
    assert "&H00000000" in ass


def test_style_from_config_uses_channel_values() -> None:
    from agent.core.channel_config import SubtitleConfig

    style = style_from_config(
        SubtitleConfig(font_size=80, highlight_color="#FF0000", margin_v=200)
    )
    assert style.font_size == 80
    assert style.highlight_color == "#FF0000"
    assert style.margin_v == 200
