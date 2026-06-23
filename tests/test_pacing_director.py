"""Tests PacingDirector."""

from __future__ import annotations

from unittest.mock import MagicMock

from agent.core.database import Scenario
from agent.skills.video.pacing_director import apply_pacing_director


def test_hook_beat_gets_punch_zoom() -> None:
    ctx = MagicMock()
    ctx.is_short_project = True
    ctx.derivation_short_index = None
    scenario = Scenario(
        project_id=MagicMock(),
        segments=[
            {
                "order": 1,
                "mood": "energique",
                "delivery_style": {"emphasis_words": ["secret"]},
                "visual_beats": [
                    {"order": 1, "visual_type": "documentary_photo", "phrase_anchor": "Le secret"},
                    {"order": 2, "visual_type": "documentary_photo", "phrase_anchor": "suite"},
                ],
            }
        ],
    )
    hints = apply_pacing_director(ctx, scenario)
    assert hints[(1, 1)].motion_hint == "punch_zoom"
    assert hints[(1, 1)].transition_hint == "pixelize"


def test_no_repeated_motion_styles() -> None:
    ctx = MagicMock()
    ctx.is_short_project = True
    ctx.derivation_short_index = None
    scenario = Scenario(
        project_id=MagicMock(),
        segments=[
            {
                "order": 1,
                "visual_beats": [
                    {"order": i, "visual_type": "documentary_photo", "phrase_anchor": f"b{i}"}
                    for i in range(1, 5)
                ],
            }
        ],
    )
    hints = apply_pacing_director(ctx, scenario)
    motions = [hints[(1, i)].motion_hint for i in range(1, 5)]
    for a, b in zip(motions, motions[1:], strict=False):
        assert a != b


def test_long_hook_gets_fadewhite_and_punch() -> None:
    ctx = MagicMock()
    ctx.is_short_project = False
    ctx.derivation_short_index = None
    scenario = Scenario(
        project_id=MagicMock(),
        segments=[
            {
                "order": 1,
                "mood": "calme",
                "visual_beats": [
                    {"order": 1, "visual_type": "documentary_photo", "phrase_anchor": "intro"},
                ],
            }
        ],
    )
    hints = apply_pacing_director(ctx, scenario)
    assert hints[(1, 1)].motion_hint == "punch_zoom"
    assert hints[(1, 1)].transition_hint == "fadewhite"


def test_long_mood_transition_from_config() -> None:
    ctx = MagicMock()
    ctx.is_short_project = False
    ctx.derivation_short_index = None
    scenario = Scenario(
        project_id=MagicMock(),
        segments=[
            {
                "order": 2,
                "mood": "energique",
                "visual_beats": [
                    {"order": 1, "visual_type": "documentary_photo", "phrase_anchor": "suite"},
                    {"order": 2, "visual_type": "documentary_photo", "phrase_anchor": "fin"},
                ],
            }
        ],
    )
    hints = apply_pacing_director(ctx, scenario)
    assert hints[(2, 1)].transition_hint == "wipeleft"

