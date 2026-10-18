"""Prosodie Azure : un mood de ligne choisit le style quand aucun style explicite n'est donné (studio voix)."""

from __future__ import annotations

from agent.skills.audio.ssml_builder import build_azure_ssml

VOICE = "fr-FR-DeniseNeural"


def test_mood_drives_the_style_when_no_explicit_style() -> None:
    ssml = build_azure_ssml("Personne n'en a parlé.", VOICE, mood="mysterieux", default_style="")
    assert 'style="whispering"' in ssml


def test_explicit_style_still_wins_over_mood() -> None:
    ssml = build_azure_ssml("Personne n'en a parlé.", VOICE, mood="mysterieux", default_style="cheerful")
    assert 'style="cheerful"' in ssml and 'style="whispering"' not in ssml
