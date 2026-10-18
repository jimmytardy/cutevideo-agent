"""Texte de publication par plateforme (agent/skills/publisher/texts.py::platform_text)."""

from __future__ import annotations

from agent.skills.publisher.texts import platform_text

TITLE = "La tortue qui respire par les fesses"
DESCRIPTION = "Une tortue australienne respire par le cloaque.\n\n#shorts #animaux\n\nCrédits :\n- Photo par X via Pexels"
CAPTIONS = {"tiktok": "Cette tortue respire… par où ?!", "instagram": "Elle respire par les fesses. Vous y croyez ?"}


def test_youtube_keeps_the_full_description() -> None:
    assert platform_text("youtube", TITLE, DESCRIPTION, CAPTIONS) == DESCRIPTION


def test_tiktok_and_instagram_use_their_dedicated_captions() -> None:
    assert platform_text("tiktok", TITLE, DESCRIPTION, CAPTIONS) == CAPTIONS["tiktok"]
    assert platform_text("instagram", TITLE, DESCRIPTION, CAPTIONS) == CAPTIONS["instagram"]


def test_fallbacks_without_captions() -> None:
    assert platform_text("tiktok", TITLE, DESCRIPTION, None) == TITLE
    # Sans légende dédiée : la description sans la ligne de hashtags (ré-ajoutés par build_caption) ni les crédits.
    assert platform_text("instagram", TITLE, DESCRIPTION, {}) == "Une tortue australienne respire par le cloaque."
    assert platform_text("instagram", TITLE, "", None) == TITLE
