from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pytest

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


@pytest.mark.asyncio
async def test_persist_plan_creates_every_short_even_derived(monkeypatch) -> None:
    """Studio ne dérive pas de shorts d'un long : chaque short planifié devient un projet."""
    from unittest.mock import AsyncMock, MagicMock

    from agent.agents import content_planner_agent as cpa

    plan = build_heuristic_plan(
        _channel(),
        production_date=date(2026, 5, 18),
        target_publish_date=date(2026, 5, 19),
        long_count=1,
        short_count=2,
        default_long_s=1800,
        default_short_s=60,
        history=[],
        evergreen=["Événement méconnu", "Biographie courte"],
    )
    assert any(s.parent_long_index == 0 for s in plan.short_videos)

    added: list = []
    session = MagicMock()
    session.add = added.append
    session.commit = AsyncMock()
    factory = MagicMock()
    factory.__aenter__ = AsyncMock(return_value=session)
    factory.__aexit__ = AsyncMock(return_value=None)
    monkeypatch.setattr(cpa, "AsyncSessionFactory", MagicMock(return_value=factory))
    monkeypatch.setattr(
        cpa, "resolve_channel_config", lambda _c: SimpleNamespace(production_mode="mixed", short_duration_s=60)
    )

    channel = SimpleNamespace(id=None, slug="test-ch", config={})
    created = await cpa.ContentPlannerAgent()._persist_plan(channel, plan, date(2026, 5, 19), date(2026, 5, 18))

    assert created == 3
    assert [p.config["format"] for p in added].count("short_standalone") == 2
