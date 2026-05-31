from __future__ import annotations

from datetime import date
from types import SimpleNamespace

from agent.skills.content_planning.heuristic_planner import build_heuristic_plan


def _channel() -> SimpleNamespace:
    return SimpleNamespace(
        slug="test-ch",
        name="Test Channel",
        theme_category="histoire",
    )


def test_heuristic_plan_respects_counts() -> None:
    plan = build_heuristic_plan(
        _channel(),
        production_date=date(2026, 5, 18),
        target_publish_date=date(2026, 5, 19),
        long_count=1,
        short_count=2,
        default_long_s=1800,
        default_short_s=60,
        history=[{"subject": "Biographie courte — exploration documentaire"}],
        evergreen=["Événement méconnu", "Biographie courte"],
    )
    assert len(plan.long_videos) == 1
    assert len(plan.short_videos) == 2
    assert plan.short_videos[0].parent_long_index == 0
    assert plan.evergreen_fallback_used is True
