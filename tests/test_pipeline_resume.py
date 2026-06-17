"""Tests résolution automatique du point de reprise pipeline."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.core.pipeline_resume import ResumePlan, next_agent_after, resolve_start_from


def test_next_agent_after_research() -> None:
    assert next_agent_after("research_agent") == "outline_agent"


def test_next_agent_after_outline() -> None:
    assert next_agent_after("outline_agent") == "scenario_agent"


def test_next_agent_after_media() -> None:
    assert next_agent_after("media_agent") == "montage_planner_agent"


def test_next_agent_after_narrator() -> None:
    assert next_agent_after("narrator_agent") == "beat_planner_agent"


def test_next_agent_after_critic() -> None:
    assert next_agent_after("critic_agent") == "clipper_agent"


def test_next_agent_after_unknown_defaults_to_research() -> None:
    assert next_agent_after("unknown_agent") == "research_agent"


@pytest.mark.asyncio
async def test_resolve_start_from_no_runs() -> None:
    project_id = uuid.uuid4()

    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = []

    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=mock_result)

    mock_factory = MagicMock()
    mock_factory.__aenter__ = AsyncMock(return_value=mock_session)
    mock_factory.__aexit__ = AsyncMock(return_value=None)

    with patch("agent.core.pipeline_resume.AsyncSessionFactory", return_value=mock_factory):
        plan = await resolve_start_from(project_id)

    assert plan == ResumePlan(step="research_agent", iteration=1)


@pytest.mark.asyncio
async def test_resolve_start_from_media_success() -> None:
    project_id = uuid.uuid4()
    media_run = MagicMock()
    media_run.agent_name = "media_agent"
    media_run.status = "success"
    media_run.iteration = 1

    scenario_run = MagicMock()
    scenario_run.agent_name = "scenario_agent"
    scenario_run.status = "success"
    scenario_run.iteration = 1

    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = [scenario_run, media_run]

    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=mock_result)

    mock_factory = MagicMock()
    mock_factory.__aenter__ = AsyncMock(return_value=mock_session)
    mock_factory.__aexit__ = AsyncMock(return_value=None)

    with patch("agent.core.pipeline_resume.AsyncSessionFactory", return_value=mock_factory):
        plan = await resolve_start_from(project_id)

    assert plan == ResumePlan(step="montage_planner_agent", iteration=1)


@pytest.mark.asyncio
async def test_resolve_start_from_ignores_running_agent() -> None:
    """Seuls les runs success comptent — narrateur running ne change pas le point de reprise."""
    project_id = uuid.uuid4()
    media_run = MagicMock()
    media_run.agent_name = "media_agent"
    media_run.status = "success"
    media_run.iteration = 1

    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = [media_run]

    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=mock_result)

    mock_factory = MagicMock()
    mock_factory.__aenter__ = AsyncMock(return_value=mock_session)
    mock_factory.__aexit__ = AsyncMock(return_value=None)

    with patch("agent.core.pipeline_resume.AsyncSessionFactory", return_value=mock_factory):
        plan = await resolve_start_from(project_id)

    assert plan.step == "montage_planner_agent"
