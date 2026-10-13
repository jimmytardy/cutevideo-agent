from __future__ import annotations

from studio.align import align_words


def _w(word: str, start: float, end: float) -> dict:
    return {"word": word, "start": start, "end": end}


def test_align_keeps_timings_and_fixes_spelling() -> None:
    words = [_w("Un", 0.0, 0.2), _w("flamand", 0.2, 0.6), _w("rose", 0.6, 0.9)]
    aligned = align_words(words, "Un flamant rose.")
    assert [w["word"] for w in aligned] == ["Un", "flamant", "rose."]
    assert aligned[1]["start"] == 0.2 and aligned[1]["end"] == 0.6


def test_align_spreads_uneven_replacements() -> None:
    words = [_w("en", 0.0, 0.2), _w("2024", 0.2, 1.0), _w("ici", 1.0, 1.2)]
    aligned = align_words(words, "en deux mille vingt-quatre ici")
    assert [w["word"] for w in aligned] == ["en", "deux", "mille", "vingt-quatre", "ici"]
    assert aligned[1]["start"] == 0.2 and aligned[3]["end"] == 1.0


def test_align_drops_unscripted_words() -> None:
    words = [_w("euh", 0.0, 0.1), _w("Bonjour", 0.1, 0.5)]
    assert [w["word"] for w in align_words(words, "Bonjour")] == ["Bonjour"]
