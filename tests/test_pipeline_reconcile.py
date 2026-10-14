"""Tests réconciliation des pipelines fantômes."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.core.pipeline_reconcile import reconcile_orphan_running_projects


def _make_project(project_id: uuid.UUID) -> MagicMock:
    project = MagicMock()
    project.id = project_id
    project.channel_id = uuid.uuid4()
    return project


@pytest.mark.asyncio
async def test_reconcile_skips_project_with_active_lease() -> None:
    project_id = uuid.uuid4()
    project = _make_project(project_id)

    projects_result = MagicMock()
    projects_result.scalars.return_value.all.return_value = [project]

    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=projects_result)
    mock_session.get = AsyncMock()

    mock_factory = MagicMock()
    mock_factory.__aenter__ = AsyncMock(return_value=mock_session)
    mock_factory.__aexit__ = AsyncMock(return_value=None)

    with (
        patch("agent.core.pipeline_reconcile.AsyncSessionFactory", return_value=mock_factory),
        patch("agent.core.pipeline_reconcile.queue.connect", new=AsyncMock()),
        patch(
            "agent.core.pipeline_reconcile.has_active_lease",
            new=AsyncMock(return_value=True),
        ),
        patch("agent.core.pipeline_reconcile.is_queued", new=AsyncMock(return_value=False)),
        patch(
            "agent.core.pipeline_reconcile.enqueue_pipeline_task",
            new=AsyncMock(),
        ) as mock_enqueue,
        patch(
            "agent.core.pipeline_reconcile.stop_running_agent_runs",
            new=AsyncMock(),
        ) as mock_stop,
    ):
        count = await reconcile_orphan_running_projects(worker_id="worker-test")

    assert count == 0
    mock_stop.assert_not_awaited()
    mock_enqueue.assert_not_awaited()


@pytest.mark.asyncio
async def test_reconcile_requeues_orphan_without_lease() -> None:
    project_id = uuid.uuid4()
    channel_id = uuid.uuid4()
    user_id = uuid.uuid4()
    project = _make_project(project_id)
    project.channel_id = channel_id

    channel = MagicMock()
    channel.user_id = user_id

    projects_result = MagicMock()
    projects_result.scalars.return_value.all.return_value = [project]

    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=projects_result)
    mock_session.get = AsyncMock(return_value=channel)

    mock_factory = MagicMock()
    mock_factory.__aenter__ = AsyncMock(return_value=mock_session)
    mock_factory.__aexit__ = AsyncMock(return_value=None)

    with (
        patch("agent.core.pipeline_reconcile.AsyncSessionFactory", return_value=mock_factory),
        patch("agent.core.pipeline_reconcile.queue.connect", new=AsyncMock()),
        patch(
            "agent.core.pipeline_reconcile.has_active_lease",
            new=AsyncMock(return_value=False),
        ),
        patch("agent.core.pipeline_reconcile.is_queued", new=AsyncMock(return_value=False)),
        patch(
            "agent.core.pipeline_reconcile.stop_running_agent_runs",
            new=AsyncMock(return_value=1),
        ) as mock_stop,
        patch(
            "agent.core.pipeline_reconcile.enqueue_pipeline_task",
            new=AsyncMock(),
        ) as mock_enqueue,
    ):
        count = await reconcile_orphan_running_projects(worker_id="worker-test")

    assert count == 1
    mock_stop.assert_awaited_once_with(
        project_id,
        reason="Worker interrompu — reprise automatique",
    )
    mock_enqueue.assert_awaited_once_with(
        project_id,
        user_id=user_id,
        reconcile_orphan=True,
    )
