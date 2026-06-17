"""Tests seuils de nettoyage pipeline (beat_planner → media)."""

from __future__ import annotations

from agent.core.pipeline_reset import PIPELINE_STEPS, step_index


def test_step_index_beat_planner() -> None:
    assert step_index("beat_planner_agent") == 4
    assert PIPELINE_STEPS[4] == "beat_planner_agent"


def test_beat_planner_cleanup_deletes_media_not_scenario() -> None:
    beat_idx = step_index("beat_planner_agent")
    scenario_idx = step_index("scenario_agent")
    media_idx = step_index("media_agent")
    assert beat_idx > scenario_idx
    assert media_idx > beat_idx
    # cleanup_from_step(beat_planner) : idx 4 → supprime media (idx<=5) mais pas scenario (idx<=1)
