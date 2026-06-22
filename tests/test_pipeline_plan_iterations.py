"""Tests plan pipeline — itérations critique."""

from __future__ import annotations

from agent.core.channel_config import ChannelRuntimeConfig
from agent.core.pipeline_plan import plan_pipeline


def test_plan_pipeline_long_unlimited_flag() -> None:
    cfg = ChannelRuntimeConfig()
    plan = plan_pipeline(cfg, project_format=None, target_duration_seconds=1800, effective_max=None)
    assert plan["max_iterations"] == 5
    assert plan["max_iterations_unlimited"] is True


def test_plan_pipeline_long_explicit_cap() -> None:
    cfg = ChannelRuntimeConfig()
    plan = plan_pipeline(cfg, project_format=None, target_duration_seconds=1800, effective_max=8)
    assert plan["max_iterations"] == 8
    assert plan["max_iterations_unlimited"] is False


def test_plan_pipeline_short_caps_at_two_even_when_unlimited() -> None:
    cfg = ChannelRuntimeConfig()
    plan = plan_pipeline(cfg, project_format="short", target_duration_seconds=60, effective_max=None)
    assert plan["max_iterations"] == 2
    assert plan["max_iterations_unlimited"] is False
