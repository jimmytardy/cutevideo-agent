"""Tests orchestrator research agent integration."""

from agent.agents.scenario_agent import (
    _format_content_plan_block,
    _format_research_block,
)
from agent.core.orchestrator import AGENT_ORDER
from agent.core.pipeline_reset import PIPELINE_STEPS


def test_agent_order_starts_with_research() -> None:
    assert AGENT_ORDER[0] == "research_agent"
    assert AGENT_ORDER[1] == "scenario_agent"


def test_pipeline_steps_include_research() -> None:
    assert PIPELINE_STEPS[0] == "research_agent"
    assert "scenario_agent" in PIPELINE_STEPS


def test_format_content_plan_block_includes_entities() -> None:
    block = _format_content_plan_block({
        "subject": "La bataille de Verdun",
        "provisional_title": "Verdun 1916",
        "sub_theme": "Première Guerre mondiale",
        "angle": "Angle tactique",
        "narrative_format": "récit",
        "main_entities": ["Verdun", "Pétain"],
        "seo_keywords": ["verdun", "1916"],
    })
    assert "La bataille de Verdun" in block
    assert "Verdun" in block
    assert "verdun" in block


def test_format_research_block() -> None:
    block = _format_research_block({
        "subject_entity": "Verdun",
        "key_facts": ["Durée : 10 mois"],
        "confidence": 0.8,
        "sources": [{"title": "BNF", "url": "https://gallica.bnf.fr"}],
    })
    assert "RECHERCHE FACTUELLE" in block
    assert "Durée : 10 mois" in block
    assert "BNF" in block
