from __future__ import annotations

from datetime import date

from agent.core.llm_config import is_engagement_run_day, is_planner_llm_day


def test_engagement_run_day_monday() -> None:
    assert is_engagement_run_day(date(2026, 5, 18)) is True


def test_engagement_run_day_thursday() -> None:
    assert is_engagement_run_day(date(2026, 5, 21)) is True


def test_engagement_run_day_tuesday() -> None:
    assert is_engagement_run_day(date(2026, 5, 19)) is False


def test_planner_llm_same_weekdays() -> None:
    assert is_planner_llm_day(date(2026, 5, 18)) is True
    assert is_planner_llm_day(date(2026, 5, 20)) is False
