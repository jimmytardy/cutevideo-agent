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
            "agent.core.pipeline_reconcile.queue.clear_agent_statuses",
            new=AsyncMock(),
        ) as mock_clear,
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
    mock_clear.assert_awaited_once_with(str(project_id))
    mock_enqueue.assert_awaited_once_with(
        project_id,
        user_id=user_id,
        reconcile_orphan=True,
    )


@pytest.mark.asyncio
async def test_enqueue_resolves_start_from_when_not_provided() -> None:
    from agent.core.pipeline_queue import enqueue_pipeline_task

    project_id = uuid.uuid4()
    channel_id = uuid.uuid4()
    user_id = uuid.uuid4()

    project = MagicMock()
    project.id = project_id
    project.status = "pending"
    project.channel_id = channel_id
    project.config = {}

    channel = MagicMock()
    channel.id = channel_id
    channel.user_id = user_id

    mock_session = AsyncMock()
    mock_session.get = AsyncMock(side_effect=lambda _model, _id: project if _id == project_id else channel)
    mock_session.commit = AsyncMock()

    mock_factory = MagicMock()
    mock_factory.__aenter__ = AsyncMock(return_value=mock_session)
    mock_factory.__aexit__ = AsyncMock(return_value=None)

    mock_redis = AsyncMock()
    mock_redis.zscore = AsyncMock(return_value=None)
    mock_redis.set = AsyncMock()
    mock_redis.zadd = AsyncMock()

    with (
        patch("agent.core.pipeline_queue.AsyncSessionFactory", return_value=mock_factory),
        patch("agent.core.pipeline_queue.queue") as mock_queue,
        patch(
            "agent.core.pipeline_queue._resolve_queue_priority",
            new=AsyncMock(return_value=10),
        ),
        patch(
            "agent.core.pipeline_queue._set_project_queued",
            new=AsyncMock(),
        ),
        patch(
            "agent.core.pipeline_queue.get_queue_status",
            new=AsyncMock(
                return_value=MagicMock(position=1, queue_length=1, priority=10, queued_at=None)
            ),
        ),
        patch(
            "agent.core.pipeline_queue.resolve_start_from",
            new=AsyncMock(return_value=MagicMock(step="narrator_agent", iteration=1)),
        ) as mock_resolve,
    ):
        mock_queue.connect = AsyncMock()
        mock_queue.clear_pipeline_cancel = AsyncMock()
        mock_queue.client = mock_redis
        await enqueue_pipeline_task(project_id, user_id=user_id)

    mock_resolve.assert_awaited_once_with(project_id)
    payload_call = mock_redis.set.call_args
    assert payload_call is not None
    import json

    payload = json.loads(payload_call.args[1])
    assert payload["start_from"] == "narrator_agent"
