from __future__ import annotations

from datetime import date

from agent.core.llm_config import is_planner_llm_day


def test_planner_llm_days_monday_and_thursday() -> None:
    assert is_planner_llm_day(date(2026, 5, 18)) is True
    assert is_planner_llm_day(date(2026, 5, 21)) is True
    assert is_planner_llm_day(date(2026, 5, 20)) is False
