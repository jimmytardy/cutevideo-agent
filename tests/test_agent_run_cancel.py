from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.core.base_agent import stop_running_agent_runs


@pytest.mark.asyncio
async def test_stop_running_agent_runs_marks_all_in_flight() -> None:
    project_id = uuid.uuid4()
    run = MagicMock()
    run.id = uuid.uuid4()
    run.agent_name = "narrator_agent"
    run.status = "running"

    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = [run]

    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=mock_result)
    mock_session.commit = AsyncMock()

    mock_factory = MagicMock()
    mock_factory.__aenter__ = AsyncMock(return_value=mock_session)
    mock_factory.__aexit__ = AsyncMock(return_value=None)

    with patch("agent.core.base_agent.AsyncSessionFactory", return_value=mock_factory):
        count = await stop_running_agent_runs(project_id)

    assert count == 1
    assert run.status == "stopped"
    assert run.error == "Arrêté manuellement"
    assert run.ended_at is not None
    mock_session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_stop_running_agent_runs_noop_when_none_running() -> None:
    project_id = uuid.uuid4()

    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = []

    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=mock_result)
    mock_session.commit = AsyncMock()

    mock_factory = MagicMock()
    mock_factory.__aenter__ = AsyncMock(return_value=mock_session)
    mock_factory.__aexit__ = AsyncMock(return_value=None)

    with patch("agent.core.base_agent.AsyncSessionFactory", return_value=mock_factory):
        count = await stop_running_agent_runs(project_id)

    assert count == 0
    mock_session.commit.assert_not_awaited()
