"""Tests résolution snapshot scénario par AgentRun."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from agent.core.scenario_snapshot import (
    resolve_scenario_id_for_agent_run,
    scenario_id_from_agent_run,
)


@dataclass
class _FakeAgentRun:
    output_json: dict | None = None
    input_json: dict | None = field(default_factory=dict)
    agent_name: str | None = None
    started_at: datetime | None = None
    ended_at: datetime | None = None


def test_scenario_id_from_output_scenario_id() -> None:
    sid = uuid.uuid4()
    run = _FakeAgentRun(output_json={"scenario_id": str(sid)})
    assert scenario_id_from_agent_run(run) == sid


def test_scenario_id_from_output_new_scenario_id() -> None:
    sid = uuid.uuid4()
    run = _FakeAgentRun(output_json={"new_scenario_id": str(sid)})
    assert scenario_id_from_agent_run(run) == sid


def test_scenario_id_prefers_new_scenario_id_over_scenario_id() -> None:
    old_id = uuid.uuid4()
    new_id = uuid.uuid4()
    run = _FakeAgentRun(
        output_json={
            "scenario_id": str(old_id),
            "new_scenario_id": str(new_id),
        }
    )
    assert scenario_id_from_agent_run(run) == new_id


def test_scenario_id_falls_back_to_input_json() -> None:
    sid = uuid.uuid4()
    run = _FakeAgentRun(
        output_json={"segments": 2},
        input_json={"scenario_id": str(sid)},
    )
    assert scenario_id_from_agent_run(run) == sid


def test_scenario_id_returns_none_when_missing() -> None:
    assert scenario_id_from_agent_run(None) is None
    assert scenario_id_from_agent_run(_FakeAgentRun()) is None


@pytest.mark.asyncio
async def test_resolve_uses_new_scenario_id_from_output() -> None:
    input_id = uuid.uuid4()
    output_id = uuid.uuid4()
    project_id = uuid.uuid4()
    run = _FakeAgentRun(
        agent_name="hook_optimizer_agent",
        output_json={"new_scenario_id": str(output_id), "segments_count": 2},
        input_json={"scenario_id": str(input_id)},
    )
    session = AsyncMock()

    resolved = await resolve_scenario_id_for_agent_run(run, project_id, session)

    assert resolved == output_id
    session.execute.assert_not_called()


@pytest.mark.asyncio
async def test_resolve_falls_back_to_scenario_created_during_hook_run() -> None:
    input_id = uuid.uuid4()
    created_id = uuid.uuid4()
    project_id = uuid.uuid4()
    started = datetime(2026, 6, 15, 18, 28, 0, tzinfo=timezone.utc)
    ended = started + timedelta(seconds=5)
    run = _FakeAgentRun(
        agent_name="hook_optimizer_agent",
        output_json={"segments": 2},
        input_json={"scenario_id": str(input_id)},
        started_at=started,
        ended_at=ended,
    )
    session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = created_id
    session.execute = AsyncMock(return_value=mock_result)

    resolved = await resolve_scenario_id_for_agent_run(run, project_id, session)

    assert resolved == created_id
    session.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_resolve_keeps_input_when_no_scenario_created_during_run() -> None:
    input_id = uuid.uuid4()
    project_id = uuid.uuid4()
    started = datetime(2026, 6, 15, 18, 28, 0, tzinfo=timezone.utc)
    run = _FakeAgentRun(
        agent_name="hook_optimizer_agent",
        output_json={"segments": 2},
        input_json={"scenario_id": str(input_id)},
        started_at=started,
        ended_at=started + timedelta(seconds=1),
    )
    session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    session.execute = AsyncMock(return_value=mock_result)

    resolved = await resolve_scenario_id_for_agent_run(run, project_id, session)

    assert resolved == input_id


@pytest.mark.asyncio
async def test_resolve_skips_temporal_fallback_for_diagram_specialist() -> None:
    input_id = uuid.uuid4()
    project_id = uuid.uuid4()
    run = _FakeAgentRun(
        agent_name="diagram_specialist_agent",
        output_json={"segments": 1},
        input_json={"scenario_id": str(input_id)},
        started_at=datetime.now(timezone.utc),
    )
    session = AsyncMock()

    resolved = await resolve_scenario_id_for_agent_run(run, project_id, session)

    assert resolved == input_id
    session.execute.assert_not_called()
