"""Tests oralisation du texte de narration pour TTS."""

from __future__ import annotations

import pytest

from agent.skills.audio.oralize import _HAS_NUM2WORDS, oralize_text


def test_oralize_strips_markdown() -> None:
    out = oralize_text("Voici un **mot** important et un `code` inline.")
    assert "*" not in out
    assert "`" not in out
    assert "mot" in out
    assert "code" in out


def test_oralize_expands_units() -> None:
    out = oralize_text("La voiture roule à 120 km/h dans une zone de 30 km.")
    assert "kilomètres heure" in out
    assert "km/h" not in out
    assert "kilomètres" in out


def test_oralize_expands_percent() -> None:
    out = oralize_text("Près de 75 % des gens ignorent ce fait.")
    assert "pour cent" in out
    assert "%" not in out


def test_oralize_empty_text_is_noop() -> None:
    assert oralize_text("") == ""
    assert oralize_text("   ") == "   "


def test_oralize_splits_long_sentence() -> None:
    long_sentence = (
        "Le premier explorateur partit vers le grand nord lointain avec ses hommes "
        "courageux et ses chiens robustes pendant le long hiver glacial, "
        "et il découvrit alors un vaste territoire totalement inconnu rempli "
        "de glaciers immenses et de paysages spectaculaires absolument magnifiques."
    )
    out = oralize_text(long_sentence)
    # La conjonction « , et » devient une nouvelle phrase « . Et »
    assert ". Et" in out


@pytest.mark.skipif(not _HAS_NUM2WORDS, reason="num2words non installé")
def test_oralize_converts_numbers_to_words() -> None:
    out = oralize_text("La Révolution française commence en 1789.")
    assert "1789" not in out
    assert "cent" in out.lower()


def test_oralize_keeps_numbers_when_num2words_absent() -> None:
    # Sans num2words, les chiffres sont conservés sans erreur.
    if _HAS_NUM2WORDS:
        pytest.skip("num2words présent — comportement testé ailleurs")
    out = oralize_text("Année 1789.")
    assert "1789" in out
