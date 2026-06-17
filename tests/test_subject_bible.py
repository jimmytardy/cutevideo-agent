from __future__ import annotations

from agent.skills.media_sources.ai.base import ImageGenerationRequest
from agent.skills.media_sources.ai.subject_bible import (
    beat_subject_seed,
    entity_seed,
    seed_for_attempt,
)


def test_entity_seed_is_deterministic_and_bounded() -> None:
    a = entity_seed("Nikola Tesla")
    b = entity_seed("nikola tesla")  # normalisation casse/espaces
    assert a == b
    assert a is not None and 0 <= a < 2_000_000_000


def test_entity_seed_empty_is_none() -> None:
    assert entity_seed("") is None
    assert entity_seed("   ") is None


def test_distinct_entities_get_distinct_seeds() -> None:
    assert entity_seed("Tour Eiffel") != entity_seed("Statue de la Liberté")


def test_beat_subject_seed_matches_when_entity_present() -> None:
    seed = beat_subject_seed("Nikola Tesla", "Plan large sur Tesla dans son laboratoire")
    assert seed == entity_seed("Nikola Tesla")


def test_beat_subject_seed_none_when_entity_absent() -> None:
    assert beat_subject_seed("Nikola Tesla", "Un paysage de montagne au crépuscule") is None


def test_beat_subject_seed_none_without_entity() -> None:
    assert beat_subject_seed("", "n'importe quel texte") is None


def test_seed_for_attempt_first_attempt_keeps_base() -> None:
    base = entity_seed("Tour Eiffel")
    assert seed_for_attempt(base, 1) == base
    assert seed_for_attempt(base, 2) == (base + 1) % 2_000_000_000
    assert seed_for_attempt(None, 3) is None


def test_request_carries_seed() -> None:
    from pathlib import Path

    req = ImageGenerationRequest(prompt="x", output_dir=Path("/tmp"), seed=42)
    assert req.seed == 42
    # Défaut : aucune graine imposée.
    assert ImageGenerationRequest(prompt="x", output_dir=Path("/tmp")).seed is None
