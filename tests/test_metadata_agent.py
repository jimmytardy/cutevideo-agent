from __future__ import annotations

from agent.agents.metadata_agent import build_chapters, format_chapters_block


def test_build_chapters_cumulative_timestamps() -> None:
    segments = [
        {"title": "Intro", "duration_s": 30},
        {"title": "Mécanisme", "duration_s": 90},
        {"title": "Conclusion", "duration_s": 40},
    ]
    chapters = build_chapters(segments)
    assert [c["start_s"] for c in chapters] == [0, 30, 120]
    assert [c["title"] for c in chapters] == ["Intro", "Mécanisme", "Conclusion"]


def test_format_chapters_block_requires_three() -> None:
    # < 3 chapitres → pas de bloc (règle YouTube)
    assert format_chapters_block([{"start_s": 0, "title": "A"}]) == ""
    block = format_chapters_block(
        [
            {"start_s": 0, "title": "Intro"},
            {"start_s": 30, "title": "Coeur"},
            {"start_s": 3725, "title": "Fin"},
        ]
    )
    assert "0:00 Intro" in block
    assert "0:30 Coeur" in block
    assert "1:02:05 Fin" in block  # bascule en h:mm:ss au-delà d'une heure
