from __future__ import annotations

from agent.skills.scenario.authorship_angle import (
    authorship_angle_is_valid,
    normalize_authorship_angle,
)


def test_normalize_authorship_angle_from_llm() -> None:
    data = {
        "authorship_angle": {
            "thesis": "La Tour Eiffel n'était pas prévue permanente.",
            "reason_to_watch": "Comprendre le vrai projet de 1889.",
            "intro_hook": "Et si je vous disais que la Tour devait être démontée ?",
        }
    }
    angle = normalize_authorship_angle(data)
    assert authorship_angle_is_valid(angle)
    assert "Tour Eiffel" in angle["thesis"]
    assert angle["intro_hook"]


def test_normalize_authorship_angle_fallback_content_plan() -> None:
    data: dict = {}
    plan = {"angle": "Portrait méconnu d'une figure clé\nDeuxième ligne"}
    angle = normalize_authorship_angle(data, content_plan=plan)
    assert authorship_angle_is_valid(angle)
    assert angle["thesis"] == "Portrait méconnu d'une figure clé"
    assert angle["reason_to_watch"]


def test_authorship_angle_invalid_without_sources() -> None:
    angle = normalize_authorship_angle({})
    assert not authorship_angle_is_valid(angle)
