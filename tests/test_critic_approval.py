"""Tests logique d'approbation CriticAgent."""

from __future__ import annotations

from agent.agents.critic_agent import CriticAgent


def test_resolve_decision_long_requires_global_score_only() -> None:
    assert CriticAgent._resolve_decision(
        global_score=90,
        structure_score=10,
        is_short=False,
        iteration=1,
        max_iterations=5,
        min_critic_score=90,
        min_short_structure_score=15,
    ) == "approve"

    assert CriticAgent._resolve_decision(
        global_score=89,
        structure_score=20,
        is_short=False,
        iteration=1,
        max_iterations=5,
        min_critic_score=90,
        min_short_structure_score=15,
    ) == "iterate"


def test_resolve_decision_short_requires_structure_and_global() -> None:
    assert CriticAgent._resolve_decision(
        global_score=95,
        structure_score=15,
        is_short=True,
        iteration=1,
        max_iterations=5,
        min_critic_score=90,
        min_short_structure_score=15,
    ) == "approve"

    assert CriticAgent._resolve_decision(
        global_score=95,
        structure_score=14,
        is_short=True,
        iteration=1,
        max_iterations=5,
        min_critic_score=90,
        min_short_structure_score=15,
    ) == "iterate"

    assert CriticAgent._resolve_decision(
        global_score=89,
        structure_score=18,
        is_short=True,
        iteration=1,
        max_iterations=5,
        min_critic_score=90,
        min_short_structure_score=15,
    ) == "iterate"


def test_resolve_decision_max_iterations_forces_approve() -> None:
    assert CriticAgent._resolve_decision(
        global_score=50,
        structure_score=5,
        is_short=True,
        iteration=5,
        max_iterations=5,
        min_critic_score=90,
        min_short_structure_score=15,
    ) == "approve"
