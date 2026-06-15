from __future__ import annotations

from agent.core.visual_beats_prompt import (
    build_revision_visual_beats_block,
    build_visual_beats_prompt_context,
)
from agent.skills.media_sources.ai.prompt_builder import (
    VISUAL_TYPE_REGISTRY,
    build_visual_type_catalog,
    list_visual_types,
)


def test_catalog_contains_all_registry_types_except_custom() -> None:
    catalog = build_visual_type_catalog()
    for vtype in list_visual_types():
        assert vtype in catalog, f"missing {vtype} in catalog"
    assert "custom" in catalog


def test_catalog_includes_descriptions() -> None:
    catalog = build_visual_type_catalog()
    assert "sports_action" in catalog
    assert "Action de match" in catalog
    assert "crime_documentary" in catalog


def test_sport_channel_marks_sport_types() -> None:
    catalog = build_visual_type_catalog(editorial_tone="documentaire", theme_category="sport")
    assert "sports_action *" in catalog
    assert "SPORT" in catalog


def test_every_type_has_french_description() -> None:
    for vtype, entry in VISUAL_TYPE_REGISTRY.items():
        assert entry.description_fr.strip(), f"{vtype} missing description_fr"


def test_visual_beats_prompt_context_includes_new_types() -> None:
    ctx = build_visual_beats_prompt_context("documentaire", "sport")
    rules = ctx["visual_beats_rules"]
    assert "sports_action" in rules
    assert "crime_documentary" in rules
    assert "ne jamais inventer" in rules.lower() or "jamais inventer" in rules


def test_revision_block_includes_catalog() -> None:
    block = build_revision_visual_beats_block("documentaire", "true_crime")
    assert "crime_documentary" in block
    assert "visual_type" in block.lower()
